import type { Api, TelegramClient } from "telegram";
import type { Transcriber } from "@/domain/transcriber";
import { withRateLimitRetry } from "@/application/withRateLimitRetry";
import { MESSAGES } from "@/messages";
import { getRepliedMessage, isVideoNote, isVoiceMessage, replyTo } from "@/telegram/utils";
import { saveVideoNoteFromMessage, saveVoiceFromMessage } from "@/telegram/voice";

export async function commandTranscribeVoice(
    ctx: { client: TelegramClient; message: Api.Message },
    deps: { transcriber: Transcriber },
): Promise<void> {
    const { client, message } = ctx;
    const replied = await getRepliedMessage(client, message);
    if (!replied || (!isVoiceMessage(replied) && !isVideoNote(replied))) {
        await replyTo(client, message, MESSAGES.notVoiceReply);
        return;
    }
    try {
        let filePath: string;

        if (isVideoNote(replied)) {
            filePath = await saveVideoNoteFromMessage(client, replied);
        } else {
            filePath = await saveVoiceFromMessage(client, replied);
        }

        const text = await withRateLimitRetry(ctx, () =>
            isVideoNote(replied)
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
        console.error("Error transcribing group/private convert:", error);
        await replyTo(client, message, MESSAGES.error);
    }
}
