import json


def convert_bathwick_to_new(in_path="Bathwick.json", out_path="new_routes.json"):
    """Convert old-style JSON to new format. Run as a script; do not execute at import time."""
    with open(in_path, "r", encoding="utf-8") as infile:
        old_data = json.load(infile)

    new_data = []
    for route in old_data:
        new_route = {
            "Route Num": str(route.get("Route Num", "")),
            "Inbound": {
                "In Dest": route.get("In Dest"),
                "Out Dest": route.get("Out Dest")
            },
            "Outbound": {
                "In Dest": route.get("Out Dest"),
                "Out Dest": route.get("In Dest")
            }
        }
        new_data.append(new_route)

    with open(out_path, "w", encoding="utf-8") as outfile:
        json.dump(new_data, outfile, indent=2)


if __name__ == '__main__':
    convert_bathwick_to_new()
