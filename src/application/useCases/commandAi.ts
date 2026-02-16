import type { Api, TelegramClient } from "telegram";
import type { AI } from "@/domain/ai";
import type { Transcriber } from "@/domain/transcriber";
import { withRateLimitRetry } from "@/application/withRateLimitRetry";
import { MESSAGES } from "@/messages";
import { getRepliedMessage, isVideoNote, isVoiceMessage, replyTo } from "@/telegram/utils";
import { saveVideoNoteFromMessage, saveVoiceFromMessage } from "@/telegram/voice";

function parseAiPrompt(text: string | undefined): string {
    const raw = (text ?? "").trim();
    if (!raw.startsWith("/ai")) return raw;
    return raw.replace(/^\/ai\s*/i, "").trim();
}

type TBuildPromptArgs = { userPrompt: string; replied: Api.Message } & (
    | { transcript?: undefined }
    | { transcript: string }
);
const buildPrompt = (d: TBuildPromptArgs): string => {
    const additionalInfo = ""; // `пользователя ${d.replied.contact?.firstName} ${d.replied.contact?.lastName}`;
    if ("transcript" in d) {
        d.transcript;
        return d.userPrompt
            ? `${d.userPrompt}\n\nКонтекст (расшифровка голосового сообщения${additionalInfo}):\n${d.transcript}`
            : `Ответь по содержанию голосового сообщения${additionalInfo}:\n${d.transcript}`;
    }

    return d.userPrompt
        ? `${d.userPrompt}\n\nКонтекст (сообщение${additionalInfo}):\n${d.replied.message}`
        : `Ответь по содержанию сообщения${additionalInfo}:\n${d.replied.message}`;
};

async function transcribeMessage(
    ctx: { client: TelegramClient; message: Api.Message },
    replied: Api.Message,
    transcriber: Transcriber,
): Promise<string> {
    let filePath: string;
    if (isVideoNote(replied)) {
        filePath = await saveVideoNoteFromMessage(ctx.client, replied);
    } else {
        filePath = await saveVoiceFromMessage(ctx.client, replied);
    }

    return withRateLimitRetry(ctx, () =>
        isVideoNote(replied)
            ? transcriber.transcribeFile(filePath, "video/mp4", { language: "Russian" })
            : transcriber.transcribeOggFile(filePath, { language: "Russian" }),
    ).then((t) => t.trim());
}

export async function commandAi(
    ctx: { client: TelegramClient; message: Api.Message },
    deps: { ai: AI; transcriber: Transcriber },
): Promise<void> {
    const { client, message } = ctx;
    try {
        const userPrompt = parseAiPrompt(message.message);
        const replied = await getRepliedMessage(client, message);

        let finalPrompt = userPrompt;
        if (replied) {
            if (isVoiceMessage(replied) || isVideoNote(replied)) {
                const transcript = await transcribeMessage(ctx, replied, deps.transcriber);
                finalPrompt = buildPrompt({ userPrompt, replied, transcript });
            } else {
                finalPrompt = buildPrompt({ userPrompt, replied });
            }
        }

        if (!finalPrompt) {
            await replyTo(client, message, MESSAGES.aiUsage);
            return;
        }

        const answer = await withRateLimitRetry(ctx, () => deps.ai.generateText(finalPrompt));
        await replyTo(client, message, answer);
    } catch (error) {
        console.error("Error handling /ai:", error);
        await replyTo(client, message, MESSAGES.error);
    }
}
