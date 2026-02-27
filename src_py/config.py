from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    tg_api_id: int
    tg_api_hash: str
    tg_session: str = ""
    userbot_channel_id: str = ""
    auto_transcribe_peer_ids: str = ""
    transcribe_disabled_peer_ids: str = ""
    deleted_tracker_enabled: bool = True
    groq_api_key: str = ""
    yandex_music_token: str = ""

    def get_userbot_channel_id(self) -> int | None:
        if not self.userbot_channel_id.strip():
            return None
        raw = int(self.userbot_channel_id)
        if raw < 0:
            return raw
        return int(f"-100{raw}")

    def get_auto_transcribe_peer_ids(self) -> set[str]:
        return self._parse_comma_separated(self.auto_transcribe_peer_ids)

    def get_transcribe_disabled_peer_ids(self) -> set[str]:
        return self._parse_comma_separated(self.transcribe_disabled_peer_ids)

    @staticmethod
    def _parse_comma_separated(v: str) -> set[str]:
        if not v:
            return set()
        return {s.strip() for s in v.split(",") if s.strip()}

    model_config = {"env_file_encoding": "utf-8"}


settings = Settings()
