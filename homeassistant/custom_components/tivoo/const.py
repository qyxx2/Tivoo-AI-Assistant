"""Constants for the Tivoo integration."""

DOMAIN = "tivoo"

CONF_MEDIA_DIRECTORY = "media_directory"
DEFAULT_MEDIA_DIRECTORY = "pixelart"
CONF_ESP32_HOST = "esp32_host"
CONF_TIVOO_BLUETOOTH_MAC = "tivoo_bluetooth_mac"
DEFAULT_TIVOO_BLUETOOTH_MAC = "11:75:58:97:49:98"

SERVICE_STOP_COUNTDOWN = "stop_countdown"
SERVICE_SET_VOLUME = "set_volume"
SERVICE_SET_EXPRESSION = "set_expression"
SERVICE_SET_MOOD = "set_mood"
SERVICE_SHOW_TEXT = "show_text"
SERVICE_START_COUNTDOWN = "start_countdown"
SERVICE_SET_BRIGHTNESS = "set_brightness"
SERVICE_SHOW_IMAGE = "show_image"
SERVICE_PLAY_ANIMATION = "play_animation"
SERVICE_SET_SCREEN_POWER = "set_screen_power"
SERVICE_SET_PLAYSTATE = "set_playstate"
SERVICE_SHOW_CLOCK = "show_clock"
SERVICE_SET_DATETIME = "set_datetime"
SERVICE_SET_WEATHER = "set_weather"
SERVICE_SET_LIGHT = "set_light"
SERVICE_SHOW_LYRICS = "show_lyrics"
SERVICE_SHOW_SCOREBOARD = "show_scoreboard"
SERVICE_SET_TIMER = "set_timer"
SERVICE_SET_NOISE_METER = "set_noise_meter"
SERVICE_SET_ALARM = "set_alarm"
SERVICE_SET_MEMORIAL = "set_memorial"
SERVICE_SET_AUDIO_SOURCE = "set_audio_source"
SERVICE_SET_SLEEP_MODE = "set_sleep_mode"
SERVICE_SHOW_DESIGN = "show_design"
SERVICE_SHOW_EFFECTS = "show_effects"
SERVICE_SHOW_VISUALIZATION = "show_visualization"
SERVICE_SHOW_GAME = "show_game"
SERVICE_GAME_CONTROL = "game_control"

ATTR_VOLUME = "volume"
ATTR_VALUE = "value"
ATTR_NAME = "name"
ATTR_COUNTDOWN = "countdown"
ATTR_COLOR = "color"
ATTR_BACKGROUND = "background"
ATTR_SPEED = "speed"
ATTR_STEP = "step"
ATTR_FONT_SIZE = "font_size"
ATTR_FONT = "font"
ATTR_FILE = "file"
ATTR_TIME = "time"
ATTR_CLOCK = "clock"
ATTR_TWENTYFOUR = "twentyfour"
ATTR_WEATHER = "weather"
ATTR_TEMP = "temp"
ATTR_CALENDAR = "calendar"
ATTR_HOT = "hot"
ATTR_TEMPERATURE = "temperature"
ATTR_CONDITION = "condition"
ATTR_UNIT = "unit"
ATTR_BRIGHTNESS = "brightness"
ATTR_EFFECT = "effect"
ATTR_POWER = "power"
ATTR_PLAYER1 = "player1"
ATTR_PLAYER2 = "player2"
ATTR_SLOT = "slot"
ATTR_WEEKDAYS = "weekdays"
ATTR_FREQUENCY = "frequency"
ATTR_MODE = "mode"
ATTR_NUMBER = "number"
ATTR_INDEX = "index"

MOOD_PRESETS = frozenset(
    {
        "happy",
        "sad",
        "angry",
        "love",
        "cool",
        "cry",
        "laugh",
        "sleepy",
        "shock",
        "wink",
        "sick",
        "party",
        "kiss",
        "oops",
    }
)
