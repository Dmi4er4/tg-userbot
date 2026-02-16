import { createPartFromUri, createUserContent, FileState, GoogleGenAI } from "@google/genai";
import type { TranscribeOptions, Transcriber } from "@/domain/transcriber";

export type GoogleTranscriberConfig = {
    apiKey: string;
    model?: string;
    baseUrl?: string;
};

export class GoogleGenAiTranscriber implements Transcriber {
    private readonly client: GoogleGenAI;
    private readonly model: string;

    constructor(config: GoogleTranscriberConfig) {
        if (!config.apiKey) {
            throw new Error("GOOGLE_API_KEY is required for transcription");
        }
        this.client = new GoogleGenAI({
            apiKey: config.apiKey,
            ...(config.baseUrl && { httpOptions: { baseUrl: config.baseUrl } }),
        });
        this.model = config.model ?? "gemini-2.5-flash";
    }

    async transcribeOggFile(filePath: string, options?: TranscribeOptions): Promise<string> {
        return this.transcribeFile(filePath, "audio/ogg", options);
    }

    async transcribeFile(filePath: string, mimeType: string, options?: TranscribeOptions): Promise<string> {
        const uploaded = await this.client.files.upload({
            file: filePath,
            config: { mimeType },
        });

        const fileName = uploaded.name;
        if (!fileName) {
            throw new Error("Google file upload did not return a file name");
        }

        // Wait for the file to become ACTIVE (needed for video files)
        let file = uploaded;
        while (file.state === FileState.PROCESSING) {
            await new Promise((r) => setTimeout(r, 1000));
            file = await this.client.files.get({ name: fileName });
        }
        if (file.state === FileState.FAILED) {
            throw new Error("Google file processing failed");
        }

        const language = options?.language ?? "Russian";
        const userPrompt =
            options?.prompt ??
            `You are a transcription model.
Transcribe the provided voice message into ${language} with maximum accuracy, preserving meaning and natural flow.
Do not include explanations, metadata, timestamps, or any additional text — only the transcription result`;

        const uri = file.uri;
        const uploadedMime = file.mimeType;
        if (!uri || !uploadedMime) {
            throw new Error("Google file upload did not return a URI or mimeType");
        }
        const result = await this.client.models.generateContent({
            model: this.model,
            contents: createUserContent([createPartFromUri(uri, uploadedMime), userPrompt]),
        });

        const text = (result as { text?: string }).text ?? "";
        const trimmed = typeof text === "string" ? text.trim() : "";
        if (!trimmed) throw new Error("Failed to extract transcription text from Google GenAI response");
        return trimmed;
    }
}
