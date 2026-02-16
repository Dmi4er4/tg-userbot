import type { Api, TelegramClient } from "telegram";
import { replyTo } from "@/telegram/utils";

const MAX_RETRIES = 3;

function parseRetryDelay(error: unknown): number | null {
	if (!(error instanceof Error)) return null;
	const msg = error.message || "";
	// Match "Please retry in Xs" or "retryDelay":"Xs"
	const match = msg.match(/retry\s+in\s+([\d.]+)\s*s/i) ?? msg.match(/"retryDelay"\s*:\s*"([\d.]+)s"/i);
	if (match) {
		const seconds = Number.parseFloat(match[1]);
		if (Number.isFinite(seconds) && seconds > 0) return seconds;
	}
	// Check for status 429 without parseable delay — default to 10s
	if ("status" in (error as Record<string, unknown>) && (error as Record<string, unknown>).status === 429) {
		return 10;
	}
	return null;
}

export async function withRateLimitRetry<T>(
	ctx: { client: TelegramClient; message: Api.Message },
	fn: () => Promise<T>,
): Promise<T> {
	let statusMessageSent = false;

	for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
		try {
			return await fn();
		} catch (error) {
			const delay = parseRetryDelay(error);
			if (delay === null || attempt === MAX_RETRIES) throw error;

			if (!statusMessageSent) {
				await replyTo(ctx.client, ctx.message, "Магия в процессе..").catch(() => {});
				statusMessageSent = true;
			}

			console.log(`[rate-limit] retrying in ${delay}s (attempt ${attempt + 1}/${MAX_RETRIES})`);
			await new Promise((r) => setTimeout(r, delay * 1000));
		}
	}

	throw new Error("unreachable");
}
