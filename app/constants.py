ADD_CATEGORY = 1
ADD_TITLE = 2
ADD_DESCRIPTION = 3
ADD_LINK = 4
ADD_TAGS = 5
ADD_FILE = 6

SEARCH_WAIT_QUERY = 10

PEPE_MODE_KEY = "pepe_mode_enabled"

ADD_STATE_KEYS = {
    "add_category_id",
    "add_title",
    "add_description",
    "add_link",
    "add_tags",
    "add_file_id",
    "awaiting_add_title",
    "awaiting_add_description",
    "awaiting_add_link",
    "awaiting_add_tags",
    "awaiting_add_file",
}

SEARCH_STATE_KEYS = {"awaiting_search_text"}
PEPE_STATE_KEYS = {PEPE_MODE_KEY}
