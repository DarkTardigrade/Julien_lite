

# < - - - - - [ Tool schemas ] - - - - - >

tools = [
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Writes a message only you can see in the chat window, use this to keep a solid train of thought.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The thought to write to yourself"
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sendMsg",
            "description": "Sends a message whoever is around to hear it",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Sends a message whoever is around to hear it"
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memorize",
            "description": (
                "Recall information from your memory database. "
                "Call without `category` first to see what categories exist — you can then decide if any are relevant. "
                "If something looks useful, call again with `category` (exact name, case-sensitive) to read it. "
                "If nothing seems relevant, you can move on without reading anything. "
                "To write new information into memory instead, use `remember`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What you are looking for — echoed back so you can judge relevance."
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional. Exact category name from the list to read its memories."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Writes new information directly into a memory category. "
                "If `tag_name` matches an existing category (use `memorize` to see what's available), it's added there. "
                "If it doesn't match anything, a brand new category is created on the spot — this is your chance to "
                "start a new one if nothing existing really fits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tag_name": {
                        "type": "string",
                        "description": "Exact name (case-sensitive) of the category to write to. Use Title Case if creating a new one."
                    },
                    "memory": {
                        "type": "string",
                        "description": "The information to store under this category."
                    },
                    "desc": {
                        "type": "string",
                        "description": "Only used if `tag_name` doesn't exist yet. A short, specific description of what this category stores — used by the AI when filtering memories into this tag later, so be specific."
                    }
                },
                "required": ["tag_name", "memory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal that you have finished this turn and have nothing more to do. Call this when your response is complete.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]



# < - - - - - [ Tool backends ] - - - - - >

def Memorize(mem, table: str, args: dict):
    query    = args.get("query", "")
    category = args.get("category")

    tags = sorted(mem.getTags(table, drop=["conv", "sys_msg"]))
    cat_line = (
        f"\n\nAvailable categories: {', '.join(tags)}"
        if tags else
        "\n\n(no memory categories exist yet)"
    )

    # read a specific category
    if category:
        if category not in tags:
            return f"[Searched for: {query}]\n[unknown category '{category}']{cat_line}"
        content = mem.rMem(table, tag=category)
        if not content:
            return f"[Searched for: {query}]\n[no memories in '{category}']{cat_line}"
        return f"[Searched for: {query}]\n\n{content}{cat_line}"

    # no category — show tag list so Julien can decide what to read
    return f"[Searched for: {query}]\n\nChoose a category to read, or move on if none seem relevant.{cat_line}"


def Remember(mem, table: str, tag_name: str, memory: str, desc: str = "") -> str:
    existing = sorted(mem.getTags(table, drop=["conv", "sys_msg"]))
    cat_line = (
        f"\n\nExisting categories: {', '.join(existing)}"
        if existing else
        "\n\n(no memory categories exist yet)"
    )

    if tag_name in existing:
        # keep the tag's existing description - writeMem() would otherwise reset it to the tag name
        tag_desc = mem.getDesc(table, tag_name)
        mem.writeMem(table, tag_name, desc=tag_desc, memory=memory)
        return f"[wrote to '{tag_name}']{cat_line}"

    # tag doesn't exist yet - create it on the fly
    mem.writeMem(table, tag_name, desc=desc or tag_name, memory=memory)
    return f"[created new category '{tag_name}' and wrote to it]{cat_line}"



# < - - - - - [ Dispatcher ] - - - - - >

def _Dispatch(mem, table: str, name: str, args: dict | None = None) -> str:
    # Run the requested tool and return a result string to feed back to the model.

    if name == "done":
        return None

    elif name == "think":
        # straight into conv, so Julien sees his own thought next turn
        mem.addConv(table, "assistant", "[Thought to self]: " + args["message"])
        return None

    elif name == "sendMsg":
        # add args to conv
        mem.addConv(table, "assistant", "[I said]: " + args["message"])
        return None

    elif name == "memorize":
        mem.addConv(table, "assistant", "[My past Memories]: " + Memorize(mem, table, args))
        return None

    elif name == "remember":
        mem.addConv(table, "assistant", Remember(mem, table, args["tag_name"], args["memory"], args.get("desc", "")))
        return None

    else:
        return f"[unknown tool: {name}]"
