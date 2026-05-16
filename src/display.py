import os


def get_display():
    if os.environ.get("INKY_DISPLAY"):
        from inky_emulator import auto
        return auto()
    else:
        from inky.auto import auto  # type: ignore[no-redef]
        return auto(ask_user=True, verbose=True)
