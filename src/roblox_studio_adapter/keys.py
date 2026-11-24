"""KeyCode names accepted by user_keyboard_input.

The set matches the enum published by the tool schema. Mouse buttons are
included because the schema lists them, even though mouse actions have their
own tool.
"""

from __future__ import annotations

from roblox_studio_adapter.errors import EditError

_NAMES = """
None Backspace Tab Clear Return Pause Escape Space QuotedDouble Hash Dollar
Percent Ampersand Quote LeftParenthesis RightParenthesis Asterisk Plus Comma
Minus Period Slash Zero One Two Three Four Five Six Seven Eight Nine Colon
Semicolon LessThan Equals GreaterThan Question At LeftBracket BackSlash
RightBracket Caret Underscore Backquote A B C D E F G H I J K L M N O P Q R
S T U V W X Y Z LeftCurly Pipe RightCurly Tilde Delete KeypadZero KeypadOne
KeypadTwo KeypadThree KeypadFour KeypadFive KeypadSix KeypadSeven KeypadEight
KeypadNine KeypadPeriod KeypadDivide KeypadMultiply KeypadMinus KeypadPlus
KeypadEnter KeypadEquals Up Down Right Left Insert Home End PageUp PageDown
F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 F13 F14 F15 NumLock CapsLock ScrollLock
RightShift LeftShift RightControl LeftControl RightAlt LeftAlt RightMeta
LeftMeta LeftSuper RightSuper Mode Compose Help Print SysReq Break Menu Power
Euro Undo ButtonX ButtonY ButtonA ButtonB ButtonR1 ButtonL1 ButtonR2 ButtonL2
ButtonR3 ButtonL3 ButtonStart ButtonSelect DPadLeft DPadRight DPadUp DPadDown
Thumbstick1 Thumbstick2 MouseLeftButton MouseRightButton MouseMiddleButton
MouseBackButton
""".split()

KEY_CODES = frozenset(_NAMES)

KEYBOARD_ACTIONS = frozenset({"keyDown", "keyUp", "keyPress", "textInput", "wait"})
MOUSE_ACTIONS = frozenset(
    {"moveTo", "mouseButtonDown", "mouseButtonUp", "mouseButtonClick", "scrollUp", "scrollDown", "wait"}
)
MOUSE_BUTTONS = frozenset({"left", "right"})


def require_key(code: str) -> str:
    if code not in KEY_CODES:
        raise EditError(f"{code!r} is not a key code this tool accepts. Example: E, Space, LeftShift.")
    return code
