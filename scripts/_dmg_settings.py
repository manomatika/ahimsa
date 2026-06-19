# _dmg_settings.py — dmgbuild settings module consumed by make_dmg.py.
#
# dmgbuild evaluates this file as Python with the `defines` dict injected into
# the module namespace. make_dmg.py passes:
#   app_path  — absolute path to the .app bundle to include
#   app_name  — the bundle's basename (e.g. "ManoMatika-0.0.1.app")
#
# Layout: the .app on the left, an /Applications symlink on the right, so the
# user drags the app onto Applications to install — the standard macOS idiom.
#
# No code signing or notarization is applied here; the resulting DMG is
# unsigned (see manomatika/ahimsa#26).

# `defines` injects these names; declare defaults so static analysis / a bare
# import does not NameError. dmgbuild overrides them at evaluation time.
app_path = defines.get("app_path")  # noqa: F821 — `defines` injected by dmgbuild
app_name = defines.get("app_name")  # noqa: F821

# Files placed into the image root.
files = [app_path]

# Symlinks created in the image root: name -> target.
symlinks = {"Applications": "/Applications"}

# Icon grid positions (x, y) keyed by item name in the volume root.
icon_locations = {
    app_name: (140, 120),
    "Applications": (380, 120),
}

# Window appearance.
window_rect = ((100, 100), (520, 320))
icon_size = 96
