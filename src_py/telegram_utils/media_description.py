from telethon.tl import types

from src_py.telegram_utils.utils import is_voice_message


def format_media_message(message: types.Message) -> str | None:
    media = message.media
    if media is None:
        return None

    if isinstance(media, types.MessageMediaPhoto):
        return "*photo*"

    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if isinstance(doc, types.Document):
            for attr in doc.attributes or []:
                if isinstance(attr, types.DocumentAttributeSticker):
                    return "*sticker*"

            if is_voice_message(message):
                return "*voice message*"

            for attr in doc.attributes or []:
                if isinstance(attr, types.DocumentAttributeVideo):
                    return "*video message*"

            for attr in doc.attributes or []:
                if isinstance(attr, types.DocumentAttributeAudio) and not attr.voice:
                    return "*audio file*"

            mime_type = doc.mime_type
            if mime_type:
                file_type = "file"
                for attr in doc.attributes or []:
                    if isinstance(attr, types.DocumentAttributeFilename):
                        ext = attr.file_name.rsplit(".", 1)[-1].lower() if "." in attr.file_name else ""
                        if ext:
                            file_type = f"{ext} file"
                        break
                else:
                    parts = mime_type.split("/")
                    if len(parts) == 2:
                        file_type = f"{parts[1]} file"

                return f"*{file_type}*"

            return "*file*"

    if isinstance(media, types.MessageMediaContact):
        return "*contact*"

    if isinstance(media, (types.MessageMediaGeo, types.MessageMediaVenue)):
        return "*location*"

    if isinstance(media, types.MessageMediaPoll):
        return "*poll*"

    return "*media*"
