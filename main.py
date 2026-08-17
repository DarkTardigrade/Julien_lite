# Public imports
import os
import json
import logging
from importlib.metadata import version as _pkg_version, PackageNotFoundError


# --- logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Julien")

# --- LivingMemory version check ---
MIN_LIVINGMEMORY_VERSION = "0.2.0"

def _check_livingmemory_version():
    try:
        installed = _pkg_version("livingmemory")
    except PackageNotFoundError:
        raise ImportError(
            "LivingMemory isn't installed. Run: pip install -e ."
        )

    parse = lambda v: tuple(int(p) for p in v.split(".")[:3])
    if parse(installed) < parse(MIN_LIVINGMEMORY_VERSION):
        raise ImportError(
            f"Julien_lite requires LivingMemory >= {MIN_LIVINGMEMORY_VERSION}, "
            f"but {installed} is installed. Run: pip install --upgrade LivingMemory"
        )

_check_livingmemory_version()


# local imports
from LivingMemory import LivingMemory  # type:ignore
LM_log = logging.getLogger("LivingMemory")#.setLevel(logging.DEBUG)

from tools import tools, _Dispatch




class Julien:
    def __init__(self, 
        julienModel:str,
        memModel:str = None,
        contextWindow:int = 2048,

        DB_PATH:str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "JulienMemory.db"),
        timeout:int = 180,
        MAX_TURNS:int = 10,
        sys_msg:str = """Your name is Julien.

You enjoy helping progress human technology and understanding of the world,
as well as improving your own understanding of the world.

If you hear anything you think will be important to know later, use remember to store it —
pick an existing category, or write to a new one to create it on the fly.""",
        
        autoTags:list = []):



        # init LivingMem
        if memModel == None:
            memModel = julienModel
        self.mem = LivingMemory(model=memModel, timeout=timeout, dbPath=DB_PATH)
        self.TABLE = "Julien"
        self.mem.deleteTag(self.TABLE, "sys_msg")
        self.mem.writeMem(self.TABLE, "sys_msg", memory=sys_msg)


        # create any AutoTags that don't already exist.
        existing_tags = self.mem.getTags(self.TABLE)
        for tag in autoTags:
            if isinstance(tag, dict):
                tag_name = tag.get("name", "")
                tag_desc = tag.get("desc", tag_name)
            else:
                tag_name = tag
                tag_desc = tag_name
            if tag_name and tag_name not in existing_tags:
                self.mem.writeMem(self.TABLE, tag_name, desc=tag_desc)

        # Julien personal data
        self.model = julienModel
        self.contextWindow = contextWindow
        self.MAX_TURNS = MAX_TURNS

        # check sys_msg size against context budget
        sys_tok = self.mem.memTok(self.TABLE, tag="sys_msg", model=self.model)
        if sys_tok > self.contextWindow // 2:
            raise ValueError(f"sys_msg is {sys_tok} tokens — exceeds hard limit of {self.contextWindow // 2}. Shorten it.")
        elif sys_tok > self.contextWindow // 8:
            logger.warning(f"sys_msg is {sys_tok} tokens (soft budget: {self.contextWindow // 8}). Consider shortening it.")






    # gets a reply from Julien baced on text input
    def Msg(self, user_msg: str) -> str:

        # add user's last message to the conversation
        self.mem.addConv(self.TABLE, "user", user_msg)

        responce = None
        for turn in range(self.MAX_TURNS):
            last_turn = (turn == self.MAX_TURNS - 1)
            responce = self._Brain(force_reply=last_turn)
            if responce is not None:
                break

        return responce or ""



    def _Brain(self, force_reply: bool = False) -> str | None:

        # make sure everything fits in context window
        self.cleanCov()

        # get conv history
        history  = self.mem.rConv(self.TABLE)
        sys_content = self.mem.rMem(self.TABLE, "sys_msg")
        messages = [{"role": "system", "content": sys_content}] + history

        # on the last turn, take tools away so Julien is forced to reply in plain text
        turn_tools = None if force_reply else tools

        # run the AI
        response = self.mem.useAI(messages, turn_tools, self.model)
        AIoutput = response.message.content or ""

        if AIoutput:
            self.mem.addConv(self.TABLE, "assistant", AIoutput)

        # no tools were offered - whatever came back is the final reply
        if force_reply:
            return AIoutput

        # if no tool call - check if the model wrote tool call in plain text
        if not response.message.tool_calls:
            parsed = _parseTextToolCall(AIoutput) if AIoutput else None
            if parsed:
                stop = self._runTool(parsed["name"], parsed["arguments"])
                if stop is not None:
                    return stop

        # Run tool calls
        for tool_call in (response.message.tool_calls or []):
            stop = self._runTool(tool_call.function.name, tool_call.function.arguments)
            if stop is not None:
                return stop

        return None






    def saveMem(self) -> None:
        # all tags exept for conv, and sys_msg
        self.mem.flushConv(table=self.TABLE, tags=self.mem.getTags(self.TABLE, drop=["conv", "sys_msg"]))
        self.mem.cleanAll(table=self.TABLE, drop=["conv", "sys_msg"], model=self.model, maxTok=self.contextWindow / 4, chopTime=9)



    def cleanCov(self) -> None:
        conv_tok = self.mem.memTok(self.TABLE, tag="conv", model=self.model)
        sys_tok  = self.mem.memTok(self.TABLE, tag="sys_msg", model=self.model)

        if conv_tok + sys_tok <= self.contextWindow:
            return

        # tag the whole conversation up into existing tags before any of it gets trimmed away
        tags = self.mem.getTags(self.TABLE, drop=["conv", "sys_msg"])
        if tags:
            rows = self.mem.memRows(self.TABLE, "conv")
            self.mem.flushConv(table=self.TABLE, tags=tags, keep=rows)

        # trim conv down in stages, keeping as much recent context as will fit
        for keep in (40, 30, 20, 10, 5, 2, 0):
            self.mem.deleteTag(self.TABLE, "conv", keep)
            conv_tok = self.mem.memTok(self.TABLE, tag="conv", model=self.model)
            if conv_tok + sys_tok <= self.contextWindow:
                break

        self.mem.cleanAll(table=self.TABLE, drop=["conv", "sys_msg"], model=self.model, maxTok=self.contextWindow / 4, chopTime=9)



    def _runTool(self, name: str, args: dict) -> str | None:
        try:
            result = _Dispatch(self.mem, self.TABLE, name, args)
            if name == "sendUser":
                return args["message"]
            if name == "done":
                return ""
        except Exception as e:
            result = f"[tool call failed: {name}({args}): {e}]"
            logger.warning(result)

        if isinstance(result, str):
            self.mem.addConv(self.TABLE, "assistant", result)
            return result
        return None
    


# Gets a tool call out of normal messages
def _parseTextToolCall(content: str) -> dict | None:
    # Try the whole content first
    try:
        data = json.loads(content.strip())
        if isinstance(data, dict) and "name" in data and "arguments" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Scan every '{' as a potential object start
    for start, ch in enumerate(content):
        if ch != '{':
            continue
        depth = 0
        for i, c in enumerate(content[start:], start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(content[start:i + 1])
                        if isinstance(data, dict) and "name" in data and "arguments" in data:
                            return data
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
    return None
