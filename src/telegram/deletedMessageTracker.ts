import { Api, type TelegramClient } from "telegram";
import { CustomFile } from "telegram/client/uploads";
import { formatMediaMessage } from "@/telegram/mediaDescription";
import { getSenderDisplayName } from "@/telegram/senderName";
import { getPeerLabelFromMessage } from "@/telegram/utils";

type MediaType = "photo" | "voiceNote" | "videoNote" | "document";

interface CachedMedia {
	buffer: Buffer;
	type: MediaType;
	mimeType: string;
	fileName: string;
}

interface CachedMessage {
	messageId: number;
	text: string | undefined;
	date: number;
	cachedAt: number;
	senderId: string | null;
	senderName: string;
	peer: Api.TypePeer;
	chatLabel: string;
	mediaDescription: string | null;
	media: CachedMedia | null;
	channelId: string | null;
}

const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
const EVICT_INTERVAL_MS = 60 * 60 * 1000; // 1 hour

function detectMediaType(message: Api.Message): { type: MediaType; mimeType: string; fileName: string } | null {
	const media = message.media;
	if (!media) return null;

	if (media instanceof Api.MessageMediaPhoto) {
		return { type: "photo", mimeType: "image/jpeg", fileName: "photo.jpg" };
	}

	if (media instanceof Api.MessageMediaDocument) {
		const doc = media.document;
		if (!(doc instanceof Api.Document)) return null;
		const mime = doc.mimeType || "application/octet-stream";

		// Voice message
		const isVoice = doc.attributes?.some(
			(a) => a instanceof Api.DocumentAttributeAudio && (a as Api.DocumentAttributeAudio).voice,
		);
		if (isVoice) {
			return { type: "voiceNote", mimeType: mime, fileName: "voice.ogg" };
		}

		// Video note (circle)
		const isVideoNote = doc.attributes?.some(
			(a) => a instanceof Api.DocumentAttributeVideo && (a as Api.DocumentAttributeVideo).roundMessage,
		);
		if (isVideoNote) {
			return { type: "videoNote", mimeType: mime, fileName: "video_note.mp4" };
		}

		// Regular document — try to get original filename
		const fileNameAttr = doc.attributes?.find(
			(a) => a instanceof Api.DocumentAttributeFilename,
		);
		const fileName = fileNameAttr instanceof Api.DocumentAttributeFilename
			? fileNameAttr.fileName
			: `file.${mimeToExt(mime)}`;

		return { type: "document", mimeType: mime, fileName };
	}

	return null;
}

function mimeToExt(mime: string): string {
	const map: Record<string, string> = {
		"image/jpeg": "jpg",
		"image/png": "png",
		"image/webp": "webp",
		"video/mp4": "mp4",
		"audio/ogg": "ogg",
		"audio/mpeg": "mp3",
		"application/pdf": "pdf",
	};
	return map[mime] || mime.split("/").pop() || "bin";
}

export class DeletedMessageTracker {
	private readonly client: TelegramClient;
	private readonly selfUserId: string;
	private readonly cache = new Map<string, CachedMessage>();
	private readonly readUpTo = new Map<string, number>();
	private evictTimer: ReturnType<typeof setInterval> | null = null;

	constructor(client: TelegramClient, selfUserId: string) {
		this.client = client;
		this.selfUserId = selfUserId;
	}

	start(): void {
		// Register without an event builder so GramJS passes raw updates directly
		this.client.addEventHandler(this.onRawUpdate);
		this.evictTimer = setInterval(() => this.evictExpired(), EVICT_INTERVAL_MS);
		console.log("[DeletedMessageTracker] started");
	}

	stop(): void {
		if (this.evictTimer) {
			clearInterval(this.evictTimer);
			this.evictTimer = null;
		}
	}

	async cacheMessage(message: Api.Message): Promise<void> {
		// Don't cache our own messages
		if (
			message.fromId instanceof Api.PeerUser &&
			String(message.fromId.userId) === this.selfUserId
		) {
			return;
		}

		const senderId = message.fromId instanceof Api.PeerUser
			? String(message.fromId.userId)
			: null;

		const senderName = await getSenderDisplayName(this.client, message);
		const mediaDescription = formatMediaMessage(message);
		const chatLabel = getPeerLabelFromMessage(message);

		// Download media now — it won't be available after deletion
		let cachedMedia: CachedMedia | null = null;
		const mediaInfo = detectMediaType(message);
		if (mediaInfo) {
			try {
				const downloaded = await this.client.downloadMedia(message);
				if (downloaded && Buffer.isBuffer(downloaded)) {
					cachedMedia = {
						buffer: downloaded,
						type: mediaInfo.type,
						mimeType: mediaInfo.mimeType,
						fileName: mediaInfo.fileName,
					};
				}
			} catch (err) {
				console.error("[DeletedMessageTracker] media download error:", err);
			}
		}

		const channelId = message.peerId instanceof Api.PeerChannel
			? String(message.peerId.channelId)
			: null;

		const key = this.makeCacheKey(message.id, channelId);

		this.cache.set(key, {
			messageId: message.id,
			text: message.message,
			date: message.date,
			cachedAt: Date.now(),
			senderId,
			senderName,
			peer: message.peerId,
			chatLabel,
			mediaDescription,
			media: cachedMedia,
			channelId,
		});
	}

	private onRawUpdate = (update: object): void => {
		if (update instanceof Api.UpdateReadHistoryInbox) {
			this.handleReadInbox(update);
		} else if (update instanceof Api.UpdateReadChannelInbox) {
			this.handleReadChannelInbox(update);
		} else if (update instanceof Api.UpdateDeleteMessages) {
			this.handleDeleteMessages(update);
		} else if (update instanceof Api.UpdateDeleteChannelMessages) {
			this.handleDeleteChannelMessages(update);
		} else if (update instanceof Api.UpdateEditMessage) {
			this.handleEditMessage(update);
		} else if (update instanceof Api.UpdateEditChannelMessage) {
			this.handleEditChannelMessage(update);
		}
	};

	private handleReadInbox(update: Api.UpdateReadHistoryInbox): void {
		const peerId = this.peerToString(update.peer);
		if (peerId) {
			this.readUpTo.set(peerId, update.maxId);
		}
	}

	private handleReadChannelInbox(update: Api.UpdateReadChannelInbox): void {
		this.readUpTo.set(`channel:${update.channelId}`, update.maxId);
	}

	private handleDeleteMessages(update: Api.UpdateDeleteMessages): void {
		for (const msgId of update.messages) {
			const key = this.makeCacheKey(msgId, null);
			const cached = this.cache.get(key);
			if (cached && this.isUnread(cached)) {
				this.sendToSaved("\u{1F5D1} Удалённое сообщение", cached).catch((err) =>
					console.error("[DeletedMessageTracker] forward error:", err),
				);
			}
			this.cache.delete(key);
		}
	}

	private handleDeleteChannelMessages(update: Api.UpdateDeleteChannelMessages): void {
		const channelId = String(update.channelId);
		for (const msgId of update.messages) {
			const key = this.makeCacheKey(msgId, channelId);
			const cached = this.cache.get(key);
			if (cached && this.isUnread(cached)) {
				this.sendToSaved("\u{1F5D1} Удалённое сообщение", cached).catch((err) =>
					console.error("[DeletedMessageTracker] forward error:", err),
				);
			}
			this.cache.delete(key);
		}
	}

	private handleEditMessage(update: Api.UpdateEditMessage): void {
		const msg = update.message;
		if (!(msg instanceof Api.Message)) return;

		const channelId = msg.peerId instanceof Api.PeerChannel
			? String(msg.peerId.channelId)
			: null;
		const key = this.makeCacheKey(msg.id, channelId);
		const cached = this.cache.get(key);
		if (!cached || !this.isUnread(cached)) return;

		const newText = msg.message;
		if (cached.text !== newText) {
			this.sendEditedToSaved(cached, newText).catch((err) =>
				console.error("[DeletedMessageTracker] edit forward error:", err),
			);
		}

		// Update cache with new text
		cached.text = newText;
		cached.cachedAt = Date.now();
	}

	private handleEditChannelMessage(update: Api.UpdateEditChannelMessage): void {
		const msg = update.message;
		if (!(msg instanceof Api.Message)) return;

		const channelId = msg.peerId instanceof Api.PeerChannel
			? String(msg.peerId.channelId)
			: null;
		const key = this.makeCacheKey(msg.id, channelId);
		const cached = this.cache.get(key);
		if (!cached || !this.isUnread(cached)) return;

		const newText = msg.message;
		if (cached.text !== newText) {
			this.sendEditedToSaved(cached, newText).catch((err) =>
				console.error("[DeletedMessageTracker] edit forward error:", err),
			);
		}

		cached.text = newText;
		cached.cachedAt = Date.now();
	}

	private isUnread(cached: CachedMessage): boolean {
		const peerId = cached.channelId
			? `channel:${cached.channelId}`
			: this.peerToString(cached.peer);
		if (!peerId) return true;
		const maxRead = this.readUpTo.get(peerId);
		if (maxRead === undefined) return true;
		return cached.messageId > maxRead;
	}

	private buildHeader(title: string, cached: CachedMessage): string {
		const date = new Date(cached.date * 1000);
		const dateStr = date.toISOString().replace("T", " ").substring(0, 16);
		return [
			title,
			`От: ${cached.senderName}`,
			`Чат: ${cached.chatLabel}`,
			`Время: ${dateStr}`,
		].join("\n");
	}

	private async sendToSaved(title: string, cached: CachedMessage): Promise<void> {
		const header = this.buildHeader(title, cached);

		if (cached.media) {
			const caption = cached.text ? `${header}\n\n${cached.text}` : header;
			await this.sendMedia(cached.media, caption);
		} else {
			const lines = [header];
			if (cached.text) {
				lines.push("", cached.text);
			}
			if (cached.mediaDescription) {
				lines.push(cached.mediaDescription);
			}
			if (!cached.text && !cached.mediaDescription) {
				lines.push("(пустое сообщение)");
			}
			await this.client.sendMessage("me", { message: lines.join("\n") });
		}

		console.log(
			`[DeletedMessageTracker] forwarded ${title} msg ${cached.messageId} from ${cached.senderName}`,
		);
	}

	private async sendEditedToSaved(cached: CachedMessage, newText: string | undefined): Promise<void> {
		const header = this.buildHeader("\u{270F}\u{FE0F} Изменённое сообщение", cached);

		const lines = [header, ""];
		if (cached.text) {
			lines.push(`Было:\n${cached.text}`);
		}
		if (newText) {
			lines.push(`\nСтало:\n${newText}`);
		}

		await this.client.sendMessage("me", { message: lines.join("\n") });

		console.log(
			`[DeletedMessageTracker] forwarded edit of msg ${cached.messageId} from ${cached.senderName}`,
		);
	}

	private async sendMedia(media: CachedMedia, caption: string): Promise<void> {
		const file = new CustomFile(media.fileName, media.buffer.length, "", media.buffer);

		switch (media.type) {
			case "photo":
				await this.client.sendFile("me", {
					file,
					caption,
					forceDocument: false,
				});
				break;
			case "voiceNote":
				await this.client.sendFile("me", {
					file,
					caption,
					voiceNote: true,
				});
				break;
			case "videoNote":
				// Video notes don't support captions — send text first
				await this.client.sendMessage("me", { message: caption });
				await this.client.sendFile("me", {
					file,
					videoNote: true,
				});
				break;
			default:
				await this.client.sendFile("me", {
					file,
					caption,
				});
				break;
		}
	}

	private makeCacheKey(messageId: number, channelId: string | null): string {
		if (channelId) {
			return `ch:${channelId}:${messageId}`;
		}
		return `msg:${messageId}`;
	}

	private peerToString(peer: Api.TypePeer): string | null {
		if (peer instanceof Api.PeerUser) return `user:${peer.userId}`;
		if (peer instanceof Api.PeerChat) return `chat:${peer.chatId}`;
		if (peer instanceof Api.PeerChannel) return `channel:${peer.channelId}`;
		return null;
	}

	private evictExpired(): void {
		const now = Date.now();
		let evicted = 0;
		for (const [key, cached] of this.cache) {
			if (now - cached.cachedAt > CACHE_TTL_MS) {
				this.cache.delete(key);
				evicted++;
			}
		}
		if (evicted > 0) {
			console.log(
				`[DeletedMessageTracker] evicted ${evicted} expired entries, ${this.cache.size} remaining`,
			);
		}
	}
}
