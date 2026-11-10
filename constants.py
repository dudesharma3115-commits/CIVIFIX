"""Reference data shared by the app, demo seed and templates."""
DISTRICTS = [
    "Chennai", "Chengalpattu", "Kancheepuram", "Tiruvallur", "Vellore",
    "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tirunelveli",
    "Erode", "Thanjavur", "Thoothukudi", "Kanniyakumari", "Dindigul",
]
DISTRICT_CENTERS = {
    "Chennai": (13.0827, 80.2707), "Chengalpattu": (12.6819, 79.9888),
    "Kancheepuram": (12.8342, 79.7036), "Tiruvallur": (13.1439, 79.9087),
    "Vellore": (12.9165, 79.1325), "Coimbatore": (11.0168, 76.9558),
    "Madurai": (9.9252, 78.1198), "Tiruchirappalli": (10.7905, 78.7047),
    "Salem": (11.6643, 78.1460), "Tirunelveli": (8.7139, 77.7567),
    "Erode": (11.3410, 77.7172), "Thanjavur": (10.7870, 79.1378),
    "Thoothukudi": (8.7642, 78.1348), "Kanniyakumari": (8.0883, 77.5385),
    "Dindigul": (10.3673, 77.9803),
}
DEPARTMENTS = ["Electricity", "Water Supply", "Roads & Highways", "Sanitation",
               "Public Health", "Parks & Public Spaces", "Other"]
# Which agency handles which category (shown to users, used for routing).
AGENCIES = {
    "Electricity":           {"name": "TNEB · Electricity Board",   "short": "TNEB",         "icon": "bolt",     "color": "#ffb020"},
    "Water Supply":          {"name": "TWAD / Metro Water",         "short": "Water Board",  "icon": "drop",     "color": "#38bdf8"},
    "Roads & Highways":      {"name": "Highways & Roads Dept",      "short": "Highways",     "icon": "road",     "color": "#a78bfa"},
    "Sanitation":            {"name": "Municipal Sanitation (SWM)", "short": "Sanitation",   "icon": "trash",    "color": "#34d399"},
    "Public Health":         {"name": "Public Health Dept",         "short": "Health",       "icon": "pulse",    "color": "#fb7185"},
    "Parks & Public Spaces": {"name": "Parks & Gardens Dept",       "short": "Parks",        "icon": "tree",     "color": "#4ade80"},
    "Other":                 {"name": "District Collectorate",      "short": "Collectorate", "icon": "building", "color": "#94a3b8"},
}
STATUSES = ["Submitted", "Approved", "Forwarded", "In Progress", "Resolved", "Rejected"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
ROLE_LABELS = {"citizen": "Citizen", "staff": "Department Officer",
               "district_admin": "District Admin", "superadmin": "Super Admin"}

# 24x24 stroke icons (rendered by the icon() template helper and by JS).
ICONS = {
    "home": "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
    "map": "M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14",
    "list": "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    "chart": "M4 20V10M10 20V4M16 20v-8M22 20H2",
    "bell": "M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9M10 21a2 2 0 004 0",
    "plus": "M12 5v14M5 12h14",
    "users": "M17 21v-2a4 4 0 00-4-4H7a4 4 0 00-4 4v2M10 11a4 4 0 100-8 4 4 0 000 8M21 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8",
    "building": "M4 21V4h10v17M14 9h6v12M8 8h2M8 12h2M8 16h2M3 21h18",
    "bolt": "M13 2L4 14h7l-1 8 9-12h-7l1-8z",
    "drop": "M12 2.5S5 10 5 15a7 7 0 0014 0c0-5-7-12.5-7-12.5z",
    "road": "M5 21L8 3M19 21L16 3M12 5v3M12 11v3M12 17v3",
    "trash": "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
    "pulse": "M3 12h4l2-5 4 10 2-5h6",
    "tree": "M12 22v-6M12 16c-4 0-6-2-6-5 0-2 1-3 2-4 0-3 2-5 4-5s4 2 4 5c1 1 2 2 2 4 0 3-2 5-6 5z",
    "gear": "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z",
    "check": "M5 12l5 5L20 7",
    "x": "M6 6l12 12M18 6L6 18",
    "logout": "M9 21H5V3h4M16 17l5-5-5-5M21 12H9",
    "camera": "M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2zM12 17a4 4 0 100-8 4 4 0 000 8",
    "image": "M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6M9 9.5h.01",
    "pin": "M12 21s-7-6.5-7-12a7 7 0 0114 0c0 5.5-7 12-7 12zM12 11a2.5 2.5 0 100-5 2.5 2.5 0 000 5",
    "shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12l2 2 4-4",
    "arrow": "M5 12h14M13 6l6 6-6 6",
    "search": "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
    "alert": "M12 3l10 18H2L12 3zM12 10v5M12 18h.01",
    "clock": "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
    "send": "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
    "wrench": "M14.7 6.3a4 4 0 005 5L21 13l-8 8a2.8 2.8 0 01-4-4l8-8zM14.7 6.3L17 4",
    "locate": "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v3M12 19v3M2 12h3M19 12h3",
}

# extra icons used by the account / security pages
ICONS.update({
    "lock": "M5 11h14v10H5zM8 11V7a4 4 0 018 0v4",
    "mail": "M3 6h18v12H3zM3 7l9 7 9-7",
    "download": "M12 3v12M7 10l5 5 5-5M4 21h16",
    "undo": "M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3",
    "key": "M15 7a4 4 0 11-3.9 4.9L4 19v2h3v-2h2v-2h2l1.2-1.2A4 4 0 0115 7zM16 9h.01",
    "file": "M6 3h8l5 5v13H6zM14 3v5h5M9 13h6M9 17h6",
    "user": "M12 12a4 4 0 100-8 4 4 0 000 8M4 21v-1a6 6 0 016-6h4a6 6 0 016 6v1",
})
