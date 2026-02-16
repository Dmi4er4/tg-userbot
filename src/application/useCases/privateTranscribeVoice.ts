import type { Api, TelegramClient } from "telegram";
import type { Transcriber } from "@/domain/transcriber";
import { withRateLimitRetry } from "@/application/withRateLimitRetry";
import { MESSAGES } from "@/messages";
import { isVideoNote, isVoiceMessage, replyTo } from "@/telegram/utils";
import { saveVideoNoteFromMessage, saveVoiceFromMessage } from "@/telegram/voice";

export async function privateTranscribeVoice(
    ctx: { client: TelegramClient; message: Api.Message },
    deps: { transcriber: Transcriber },
): Promise<void> {
    const { client, message } = ctx;
    if (!isVoiceMessage(message) && !isVideoNote(message)) return;
    try {
        let filePath: string;

        if (isVideoNote(message)) {
            filePath = await saveVideoNoteFromMessage(client, message);
        } else {
            filePath = await saveVoiceFromMessage(client, message);
        }

        const text = await withRateLimitRetry(ctx, () =>
            isVideoNote(message)
                ? deps.transcriber.transcribeFile(filePath, "video/mp4", { language: "Russian" })
                : deps.transcriber.transcribeOggFile(filePath, { language: "Russian" }),
        );

        const cleaned = text.trim();
        if (cleaned) {
            await replyTo(client, message, `Расшифровка:\n${cleaned}`);
        } else {
            await replyTo(client, message, "Расшифровка: <empty>");
        }
    } catch (error) {
        console.error("Error transcribing private voice/videonote:", error);
        await replyTo(client, message, MESSAGES.error);
    }
}
