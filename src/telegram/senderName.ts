import { Api, type TelegramClient } from "telegram";

async function resolveUserName(client: TelegramClient, peer: Api.PeerUser): Promise<string> {
	try {
		const user = await client.getEntity(peer);
		if (user instanceof Api.User) {
			if (user.username) {
				return `@${user.username}`;
			}
			if (user.firstName || user.lastName) {
				return [user.firstName, user.lastName]
					.filter(Boolean)
					.join(" ")
					.trim();
			}
			return `User ${user.id}`;
		}
	} catch (error) {
		console.error("Error getting sender display name:", error);
	}
	return "Unknown";
}

export async function getSenderDisplayName(
	client: TelegramClient,
	message: Api.Message,
): Promise<string> {
	if (message.fromId instanceof Api.PeerUser) {
		return resolveUserName(client, message.fromId);
	}

	// In private chats fromId is often null — the sender is the peer itself
	if (!message.fromId && message.peerId instanceof Api.PeerUser) {
		return resolveUserName(client, message.peerId);
	}

	return "Unknown";
}
