"""Text normalisation shared by the CSV importer and the API, so both agree on identity."""


def normalise_task_name(raw: str) -> str:
    """'  Pick   Cup ' -> 'pick cup'"""
    return " ".join(raw.split()).lower()


def normalise_episode_id(raw: str) -> str:
    """' ep-00003' -> 'EP-00003'"""
    return raw.strip().upper()
