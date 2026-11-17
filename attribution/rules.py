def credit(path: list[dict], rule: str) -> dict[str, float]:
    if not path:
        return {}
    channels = [item["channel"] for item in path]
    result: dict[str, float] = {}
    if rule == "last":
        result[channels[-1]] = 1.0
    elif rule == "linear":
        share = 1.0 / len(channels)
        for channel in channels:
            result[channel] = result.get(channel, 0.0) + share
    else:
        raise ValueError(f"unsupported attribution rule: {rule}")
    return result
