import { Api, type TelegramClient } from "telegram";
import { NewMessage } from "telegram/events";
import type { Handler } from "@/presentation/handlers";
import { DeletedMessageTracker } from "@/telegram/deletedMessageTracker";

export interface TgUserbotOptions {
    deletedTrackerEnabled?: boolean;
}

export class TgUserbot {
    private readonly client: TelegramClient;
    private readonly handlers: Handler;
    private readonly options: TgUserbotOptions;
    private selfUserId: string | null = null;
    private deletedMessageTracker: DeletedMessageTracker | null = null;

    constructor(client: TelegramClient, handlers: Handler, options: TgUserbotOptions = {}) {
        this.client = client;
        this.handlers = handlers;
        this.options = options;
    }

    async start(): Promise<void> {
        const me = await this.client.getMe();
        this.selfUserId = me instanceof Api.User ? String(me.id) : null;

        if (this.options.deletedTrackerEnabled !== false && me instanceof Api.User) {
            this.deletedMessageTracker = new DeletedMessageTracker(this.client, String(me.id));
            this.deletedMessageTracker.start();
        }

        this.client.addEventHandler(this.onNewMessage, new NewMessage({}));
    }

    private onNewMessage = async (event: unknown): Promise<void> => {
        const message = (event as { message?: Api.Message }).message as Api.Message | undefined;
        if (!message) return;

        // Cache message for deleted message tracking (fire-and-forget)
        if (this.deletedMessageTracker) {
            this.deletedMessageTracker.cacheMessage(message).catch((err) =>
                console.error("[DeletedMessageTracker] cache error:", err),
            );
        }

        for (const h of this.handlers) {
            try {
                const triggered = await h.isTriggered({ client: this.client, message, selfUserId: this.selfUserId });
                if (triggered) {
                    console.info(`[handler:${h.name}] started at: ${Date.now()}`);
                    await h.handler({ client: this.client, message });
                    console.info(`[handler:${h.name}] finished at: ${Date.now()}`);
                    break;
                }
            } catch (error) {
                // keep the loop resilient
                console.error(`[handler:${h.name}] errored at: ${Date.now()}, error:`, error);
            }
        }
    };
}
