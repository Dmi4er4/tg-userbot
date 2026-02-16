import { Api } from "telegram";
import { isVoiceMessage } from "@/telegram/utils";

export function formatMediaMessage(message: Api.Message): string | null {
	const media = message.media;
	if (!media) return null;

	// Photo (grouped photos are handled separately in formatMessagesWithUsernames)
	if (media instanceof Api.MessageMediaPhoto) {
		return "*photo*";
	}

	// Document-based media
	if (media instanceof Api.MessageMediaDocument) {
		const document = media.document;
		if (document instanceof Api.Document) {
			const isSticker = document.attributes?.some(
				(attr) => attr instanceof Api.DocumentAttributeSticker,
			);
			if (isSticker) {
				return "*sticker*";
			}

			// Voice message
			if (isVoiceMessage(message)) {
				return "*voice message*";
			}

			// Video
			const isVideo = document.attributes?.some(
				(attr) => attr instanceof Api.DocumentAttributeVideo,
			);
			if (isVideo) {
				return "*video message*";
			}

			// Audio (music)
			const isAudio = document.attributes?.some(
				(attr) =>
					attr instanceof Api.DocumentAttributeAudio &&
					!(attr as Api.DocumentAttributeAudio).voice,
			);
			if (isAudio) {
				return "*audio file*";
			}

			// Other documents (files)
			const mimeType = document.mimeType;
			if (mimeType) {
				let fileType = "file";
				const fileNameAttr = document.attributes?.find(
					(attr) => attr instanceof Api.DocumentAttributeFilename,
				);

				if (fileNameAttr instanceof Api.DocumentAttributeFilename) {
					const ext = fileNameAttr.fileName.split(".").pop()?.toLowerCase();
					if (ext) {
						fileType = `${ext} file`;
					}
				} else {
					const mimeParts = mimeType.split("/");
					if (mimeParts.length === 2) {
						fileType = `${mimeParts[1]} file`;
					}
				}

				return `*${fileType}*`;
			}

			return "*file*";
		}
	}

	// Contact
	if (media instanceof Api.MessageMediaContact) {
		return "*contact*";
	}

	// Location
	if (
		media instanceof Api.MessageMediaGeo ||
		media instanceof Api.MessageMediaVenue
	) {
		return "*location*";
	}

	// Poll
	if (media instanceof Api.MessageMediaPoll) {
		return "*poll*";
	}

	return "*media*";
}
