import re


class nameLookup:
    def __init__(self, client, name: tuple):
        self.names = {}
        self.client = client
        self.name = name  # Used to tell the bot what it's called

    def apiLookup(self, name):
        try:
            return self.names[name]
        except KeyError:
            self.names[name] = self.client.users_info(user=name)
            return self.names[name]

    def lookupName(self, id: str) -> str:
        name = ""
        try:
            name = self.apiLookup(id)['user']['profile']['real_name']
        except (KeyError, TypeError):
            pass
        if name != "": return name

        try:
            name = self.apiLookup(id)['user']['real_name']
        except (KeyError, TypeError):
            pass
        if name != "": return name

        try:
            name = self.apiLookup(id)['user']['profile']['name']
        except (KeyError, TypeError):
            pass
        if name != "": return name

        return "Student"  # fallback

    def RElookupName(self, match: re.Match) -> str:
        return self.lookupName(match.group(1))

    def sanitizeMessage(self, msg: str) -> str:
        new = re.sub(r"<@(.*?)>", self.RElookupName, msg)
        new = re.sub(r"<!(.*?)>", "\1", new)
        new = re.sub(self.name[0], self.name[1], new)
        return new
