import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Api, TelegramClient } from "telegram";
import { getPeerLabelFromMessage } from "@/telegram/utils";

const voicesDir = join(process.cwd(), "voices");

async function ensureVoicesDir(): Promise<void> {
    await mkdir(voicesDir, { recursive: true });
}

export function buildVoiceFileName(message: Api.Message): string {
    const peerId = getPeerLabelFromMessage(message);
    return `voice-${peerId}-${String(message.id)}-${Date.now()}.ogg`;
}

async function saveMediaFromMessage(client: TelegramClient, message: Api.Message, fileName: string): Promise<string> {
    await ensureVoicesDir();
    const destPath = join(voicesDir, fileName);
    const data = await client.downloadMedia(message, {});
    if (!data) throw new Error("Failed to download media");
    if (data instanceof Uint8Array) {
        await writeFile(destPath, Buffer.from(data));
    } else {
        throw new Error("Unexpected media type returned while downloading media");
    }
    return destPath;
}

export async function saveVoiceFromMessage(client: TelegramClient, message: Api.Message): Promise<string> {
    return saveMediaFromMessage(client, message, buildVoiceFileName(message));
}

export async function saveVideoNoteFromMessage(client: TelegramClient, message: Api.Message): Promise<string> {
    const peerId = getPeerLabelFromMessage(message);
    const fileName = `videonote-${peerId}-${String(message.id)}-${Date.now()}.mp4`;
    return saveMediaFromMessage(client, message, fileName);
}
