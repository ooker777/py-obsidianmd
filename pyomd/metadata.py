from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Optional, Type, Union

import frontmatter

from pyomd.config import CONFIG

from .exceptions import ArgTypeError, InvalidFrontmatterError

UserInput = Union[str, int, float]
MetaDict = dict[str, list[str]]
ParseFunction = Callable[[str], tuple[MetaDict, str]]
Number = Union[int, float]
from string import Template
from typing import Tuple

from pyomd.config import CONFIG


class Order(Enum):
    ASC = "asc"
    DESC = "desc"


class MetadataType(Enum):
    FRONTMATTER = "frontmatter"
    INLINE = "inline"
    ALL = "notemeta"
    DEFAULT = "default"

    @staticmethod
    def get_from_str(s: Union[str, None]) -> MetadataType:
        if s is None:
            return MetadataType.ALL
        for k in MetadataType:
            if s == k.value:
                return k
        raise ValueError(f'Metadatatype not defined: "{s}"')


class Metadata(ABC):
    def __init__(self, note_content: str):
        self.metadata: MetaDict = self.parse(note_content)

    def __repr__(self):
        r = f"{type(self)}:\n"
        if self.to_string() is None:
            r += " None"
        else:
            r += "".join([f'- {k}: {", ".join(v)}\n' for k, v in self.metadata.items()])
        return r

    @classmethod
    @abstractmethod
    def parse(
        cls, note_content: str, parse_fn: Union[ParseFunction, None] = None
    ) -> MetaDict:
        pass

    @staticmethod
    def parse_special_fields(metadata: MetaDict, meta_type: MetadataType) -> MetaDict:
        sep_field_name = f"{meta_type.value}_separators"
        for k in metadata:
            b1 = k in CONFIG.cfg["fields"]
            b2 = sep_field_name in CONFIG.cfg["fields"].get(k, {})
            if b1 and b2:
                for sep in CONFIG.cfg["fields"][k][sep_field_name]:
                    tmp = sep.join(metadata[k])
                    metadata[k] = [t.strip() for t in tmp.split(sep) if t.strip() != ""]
        return metadata

    @abstractmethod
    def to_string(self) -> str:
        """Render metadata as a string.

        If repr is True, print to screen
        """
        pass

    @abstractmethod
    def update_content(self, note_content: str) -> str:
        ...

    @classmethod
    @abstractmethod
    def erase(cls, note_content: str) -> str:
        pass

    @classmethod
    def exists(cls, note_content: str) -> bool:
        """Checks if the metadata type is present in the note"""
        try:
            meta_dict = cls.parse(note_content)
        except:
            meta_dict = {}
        return len(meta_dict) > 0

    def get(self, k: str) -> Union[list[str], None]:
        """adds a metadata field, or new values if it already exists

        If overwrite is set to True, the old value is overwritten. Otherwise, new elements are
        appended.
        """
        return self.metadata.get(k, None)

    def add(
        self,
        k: str,
        l: Union[UserInput, list[UserInput], None],
        overwrite: bool = False,
    ) -> None:
        """adds a metadata field, or new values if it already exists

        If overwrite is set to True, the old value is overwritten. Otherwise, new elements are
        appended.
        """
        if l is None:
            nl = list()
        elif isinstance(l, UserInput):
            nl = [str(l)]
        else:
            nl = [str(x) for x in l]

        if overwrite:
            self.metadata[k] = nl
        else:
            if k in self.metadata:
                self.metadata[k] += nl
            else:
                self.metadata[k] = nl

    def remove(
        self, k: str, l: Optional[Union[UserInput, list[UserInput]]] = None
    ) -> None:
        """removes a metadata field"""
        if k not in self.metadata:
            return
        if l is None:
            del self.metadata[k]
            return
        nl = [str(l)] if isinstance(l, UserInput) else [str(x) for x in l]
        self.metadata[k] = [e for e in self.metadata[k] if e not in nl]

    def remove_empty(self) -> None:
        """removes a metadata field"""
        empty: list[str] = list()
        for k in self.metadata:
            if len(self.metadata[k]) == 0:
                empty.append(k)

        for k in empty:
            del self.metadata[k]

    def remove_duplicate_values(self, k: Union[str, list[str], None] = None) -> None:

        if k is None:
            list_keys = list(self.metadata.keys())
        elif isinstance(k, str):
            list_keys = [k]
        elif isinstance(k, list):
            list_keys = k
        else:
            raise ArgTypeError(
                var_name="k",
                type_given=type(k),
                type_expected=str(Union[str, list[str], None]),
            )

        for k2 in list_keys:
            if k2 not in self.metadata:
                continue
            self.metadata[k2] = list(dict.fromkeys(self.metadata[k2]))

    def order_values(
        self, k: Union[str, list[str], None] = None, how: Order = Order.ASC
    ) -> None:
        """Orders metadata values.

        Attributes:
            - k: key on which to order the values. If None, orders all values
        """
        if not isinstance(how, Order):
            raise ArgTypeError(var_name="how", type_given=type(how), type_expected=Order)  # type: ignore

        if k is None:
            k = list(self.metadata.keys())
        if isinstance(k, str):
            k = [k]
        for e in k:
            reverse = False if (how == Order.ASC) else True
            self.metadata[e] = sorted(self.metadata[e], reverse=reverse)

    def order_keys(self, how: Order = Order.ASC) -> None:
        """Orders metadata keys.

        Utilizes that since 3.6, python dict remember insert order.
        """
        reverse = how == Order.DESC
        list_keys = sorted(list(self.metadata.keys()), reverse=reverse)
        self.metadata = {k: self.metadata.pop(k) for k in list_keys}

    def order(
        self,
        k: Union[str, list[str], None] = None,
        o_keys: Union[Order, None] = Order.ASC,
        o_values: Union[Order, None] = Order.ASC,
    ):
        """Orders metadata keys and values.

        Attributes:
            - keys: keys for which to order the values
            - o_keys: how to order the keys. If None, don't order them
            - o_values: how to order values. If None, don't order them
        """
        if o_keys is not None:
            self.order_keys(how=o_keys)
        if o_values is not None:
            self.order_values(k=k, how=o_values)
        return None

    def print(self):
        print(self.to_string())


class Frontmatter(Metadata):
    """Represents the frontmatter of a note"""

    REGEX = "(?s)(^---\n).*?(\n---\n)"

    @classmethod
    def parse(
        cls, note_content: str, parse_fn: Union[ParseFunction, None] = None
    ) -> MetaDict:
        """Parse note content to extract metadata dictionary."""
        if parse_fn is None:
            parse_fn = cls.parse_1
        return parse_fn(note_content)

    @classmethod
    def parse_1(cls, note_content: str) -> MetaDict:
        """Parse note content to extract metadata dictionary.
        Uses the python-frontmatter library."""
        try:
            fm = frontmatter.loads(note_content)
        except:
            raise InvalidFrontmatterError

        meta_dict: MetaDict = fm.metadata

        for k in meta_dict:
            if meta_dict[k] is None:
                meta_dict[k] = list()

        # make all elements into list of strings
        for k, v in meta_dict.items():
            if isinstance(v, str):
                meta_dict[k] = [v]
            if isinstance(v, Number):
                meta_dict[k] = [str(v)]
            if isinstance(v, list):
                meta_dict[k] = [str(x) for x in v]

        meta_dict = cls.parse_special_fields(
            metadata=meta_dict, meta_type=MetadataType.FRONTMATTER
        )
        return meta_dict

    @classmethod
    def parse_2(cls, note_content: str) -> MetaDict:
        """Parse frontmatter metadata using regex"""
        mtc = re.search(cls.REGEX, note_content)
        if mtc is None:
            ext_str = list()
        fm_str = mtc.group()
        ext_str = [fm_str]

        # convert extracted string to dictionary
        metadata: MetaDict = {}
        if len(ext_str) == 0:
            return {}
        ms = ext_str[0]
        elements = ms.split("\n")
        for e in elements:
            if ":" not in e:
                continue
            k, v = e.split(":", maxsplit=1)
            c = [v.strip()] if "," not in v else [x.strip() for x in v.split(",")]
            metadata[k.strip()] = c
        if "tags" in metadata:
            mtags = " ".join(metadata["tags"])
            metadata["tags"] = [t.strip() for t in mtags.split(" ") if t.strip() != ""]

        return metadata

    def to_string(self) -> str:
        """Render metadata as a string.

        If repr is True, print to screen
        """
        if len(self.metadata) == 0:
            return ""
        metadata_repr = ""
        for k, v in self.metadata.items():
            if len(v) == 1:
                metadata_repr += f"{k}: {v[0]}\n"
            else:
                metadata_repr += f'{k}: [ {", ".join(v)} ]\n'
        out = "---\n" + metadata_repr + "---\n"
        return out

    @classmethod
    def erase(cls, note_content: str) -> str:
        r: str = frontmatter.loads(note_content).content
        return r

    def update_content(self, note_content: str) -> str:
        """ """
        content_no_meta = self.erase(note_content)
        res = self.to_string() + content_no_meta
        return res


class InlineMetadata(Metadata):
    """Represents the inline metadata of a note"""

    TMP_REGEX = Template(r"(?P<beg>.*?)(?P<key>$key)::(?P<values>.*)")
    TMP_REGEX_ENCLOSED = Template(
        r"(?P<beg>.*?)(?P<open>[(\[])(?P<key>$key)::(?P<values>.*?)(?P<close>[)\]])(?P<end>.*)"
    )
    REGEX = re.compile(TMP_REGEX.substitute(key="[A-z][A-z0-9_ -]*"))
    REGEX_ENCLOSED = re.compile(TMP_REGEX_ENCLOSED.substitute(key=".*?"))

    @classmethod
    def parse(
        cls, note_content: str, parse_fn: Union[ParseFunction, None] = None
    ) -> MetaDict:
        """Parse note content to extract metadata dictionary."""
        if parse_fn is None:
            parse_fn = cls.parse_1
        return parse_fn(note_content)

    @classmethod
    def parse_1(cls, note_content: str) -> MetaDict:
        """Parse note content to extract metadata dictionary.
        Uses the python-frontmatter library."""

        matches: list[re.Match] = list()
        for l in note_content.split("\n"):
            m = cls.REGEX.search(l)
            b = m is not None
            b_enc = cls.REGEX_ENCLOSED.search(l) is not None
            if b and not b_enc:
                matches.append(m)

        tmp: dict[str, list[str]] = dict()
        for m in matches:
            k = m.group("key").strip()
            v = m.group("values")
            tmp[k] = tmp.get(k, "") + ", " + v
        metadata: MetaDict = {
            k: [x.strip() for x in v.split(",") if len(x.strip()) > 0]
            for (k, v) in tmp.items()
        }

        metadata = cls.parse_special_fields(
            metadata=metadata, meta_type=MetadataType.INLINE
        )
        return metadata

    def to_string(self, ignore_k: Union[str, list[str], None] = None) -> str:
        """Render metadata as a string.

        If repr is True, print to screen
        """
        if ignore_k is None:
            ignore_k = list()
        if isinstance(ignore_k, str):
            ignore_k = [ignore_k]
        meta_dict = {k: v for (k, v) in self.metadata.items() if k not in ignore_k}
        if len(meta_dict) == 0:
            return ""
        r = ""
        for k, v in meta_dict.items():
            r += f"{k}:: {', '.join(v)}\n"
        r = r[:-1]  # remove last \n
        return r

    @classmethod
    def erase(cls, note_content: str) -> str:
        keep: list[str] = list()
        for l in note_content.split("\n"):
            b_match = re.search(cls.REGEX, l) is not None
            b_match_enclosed = re.search(cls.REGEX_ENCLOSED, l) is not None
            if b_match and not b_match_enclosed:
                continue
            keep.append(l)
        content_no_meta = "\n".join(keep)
        return content_no_meta

    @staticmethod
    def get_sep_newlines(content_no_meta: str, how: str = "bottom") -> str:
        if how == "top":
            if len(content_no_meta) >= 1 and content_no_meta[0] != "\n":
                sep = "\n\n"
            elif len(content_no_meta) >= 1 and content_no_meta[0:2] != "\n\n":
                sep = "\n"
            else:
                sep = ""
        elif how == "bottom":
            if len(content_no_meta) >= 1 and content_no_meta[-1] != "\n":
                sep = "\n\n"
            elif len(content_no_meta) >= 2 and content_no_meta[-2:] != "\n\n":
                sep = "\n"
            else:
                sep = ""
        else:
            sep = ""
        return sep

    def update_content_inplace(self, note_content: str) -> Tuple[str, set[str]]:
        """
        Updates inline metadata in place.

        Returns a tuple:
            - updated note_content
            - list of updated fields.
        """
        updated_fields: set[str] = set()
        for k in self.metadata:
            new_v = ", ".join(self.metadata[k])
            regex_field = re.compile(self.TMP_REGEX.substitute(key=f"{k} *"))
            print(regex_field.search(note_content))
            for m in regex_field.finditer(note_content):
                print(f"gotacha: {k}")
                print(m)
                updated_fields.add(k)
                beg = m.group("beg")
                k = m.group("key")
                rep = f"{beg}{k.strip()} :: {new_v}"
                note_content = regex_field.sub(rep, note_content)
        return (note_content, updated_fields)

    def update_content(
        self, note_content: str, how: str = "bottom", inplace: bool = True
    ) -> str:
        """
        how:
            - bottom
            - top
        inplace:
            - replace inline metadata inplace (for existing fields in the note)
        """
        if inplace:
            nc, ignore_k = self.update_content_inplace(note_content=note_content)
        else:
            nc, ignore_k = self.erase(note_content), None
        sep = self.get_sep_newlines(nc, how=how)
        if how == "top":
            new_nc = self.to_string(ignore_k=ignore_k) + sep + nc
        elif how == "bottom":
            new_nc = nc + sep + self.to_string(ignore_k=ignore_k)
        else:
            new_nc = ""
            raise NotImplementedError
        new_nc = new_nc.strip()
        return new_nc


class NoteMetadata:
    """Contains all the note's metadata (frontmatter + inline)."""

    def __init__(self, note_content: str):
        self.frontmatter = Frontmatter(note_content)
        self.inline = InlineMetadata(note_content)

    @classmethod
    def _parse_arg_meta_type(cls, meta_type: Union[MetadataType, None]) -> MetadataType:
        if meta_type is None:
            meta_type = MetadataType.ALL
        if not isinstance(meta_type, MetadataType):  # type: ignore
            raise ArgTypeError(
                var_name="meta_type",
                type_given=type(meta_type),
                type_expected=str(Union[MetadataType, None]),
            )
        return meta_type

    def get_default_metadata(self, k: str):
        b1 = k in CONFIG.cfg["fields"]
        b2 = "default_meta" in CONFIG.cfg["fields"].get(k, {})
        if b1 and b2:
            meta_type = MetadataType.get_from_str(
                CONFIG.cfg["fields"][k]["default_meta"]
            )
        else:
            meta_type = MetadataType.get_from_str(CONFIG.cfg["global"]["default_meta"])
        return meta_type

    def get(
        self, k: str, meta_type: MetadataType = MetadataType.DEFAULT
    ) -> Union[list[str], None]:
        """ """
        if meta_type == MetadataType.DEFAULT:
            meta_type = self.get_default_metadata(k)
        if meta_type == MetadataType.FRONTMATTER:
            return self.frontmatter.get(k=k)
        if meta_type == MetadataType.INLINE:
            return self.frontmatter.get(k=k)

    def add(
        self,
        k: str,
        l: Union[UserInput, list[UserInput], None],
        meta_type: MetadataType = MetadataType.DEFAULT,
        overwrite: bool = False,
    ) -> None:
        """ """
        if meta_type == MetadataType.DEFAULT:
            meta_type = self.get_default_metadata(k)
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.add(k=k, l=l, overwrite=overwrite)
        if meta_type == MetadataType.INLINE:
            self.inline.add(k=k, l=l, overwrite=overwrite)

    def remove(
        self,
        k: str,
        l: Optional[Union[UserInput, list[UserInput]]] = None,
        meta_type: MetadataType = MetadataType.FRONTMATTER,
    ) -> None:
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.remove(k=k, l=l)
        if meta_type == MetadataType.INLINE:
            self.inline.remove(k=k, l=l)

    def remove_empty(
        self,
        meta_type: MetadataType = MetadataType.ALL,
    ) -> None:
        """removes metadata fields that are empty"""
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.remove_empty()
        if meta_type == MetadataType.INLINE:
            self.inline.remove_empty()
        if meta_type is MetadataType.ALL:
            self.frontmatter.remove_empty()
            self.inline.remove_empty()

    def remove_duplicate_values(
        self,
        k: Union[str, list[str], None] = None,
        meta_type: Union[MetadataType, None] = None,
    ):
        """Remove duplicate values in the note's metadata

        Attributes:
            - k: key or list of keys on which to perform the duplication removal. If None, do on all keys
            - meta_type: target Metadata type. If None, does it on all metadata
        """
        meta_type = self._parse_arg_meta_type(meta_type)
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.remove_duplicate_values(k=k)
        elif meta_type == MetadataType.INLINE:
            self.inline.remove_duplicate_values(k=k)
        elif meta_type == MetadataType.ALL:
            self.frontmatter.remove_duplicate_values(k=k)
            self.inline.remove_duplicate_values(k=k)
        else:
            raise ValueError(f"Unsupported value for argument meta_type: {meta_type}")

    def update_content(
        self, note_content: str, inline_how: str = "bottom", inline_inplace: bool = True
    ) -> str:
        str_no_fm = self.frontmatter.erase(note_content)
        res = self.inline.update_content(
            str_no_fm, how=inline_how, inplace=inline_inplace
        )
        res = self.frontmatter.to_string() + res
        return res

    def order_values(
        self,
        k: Union[str, list[str], None] = None,
        how: Order = Order.ASC,
        meta_type: Union[MetadataType, None] = None,
    ) -> None:
        meta_type = self._parse_arg_meta_type(meta_type)
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.order_values(k=k, how=how)
        elif meta_type == MetadataType.INLINE:
            self.inline.order_values(k=k, how=how)
        elif meta_type == MetadataType.ALL:
            self.frontmatter.order_values(k=k, how=how)
            self.inline.order_values(k=k, how=how)
        else:
            raise ValueError(f"Unsupported value for argument meta_type: {meta_type}")

    def order_keys(
        self, how: Order = Order.DESC, meta_type: Union[MetadataType, None] = None
    ) -> None:
        meta_type = self._parse_arg_meta_type(meta_type)
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.order_keys(how=how)
        elif meta_type == MetadataType.INLINE:
            self.inline.order_keys(how=how)
        elif meta_type == MetadataType.ALL:
            self.frontmatter.order_keys(how=how)
            self.inline.order_keys(how=how)
        else:
            raise ValueError(f"Unsupported value for argument meta_type: {meta_type}")

    def order(
        self,
        k: Union[str, list[str], None] = None,
        o_keys: Union[Order, None] = Order.ASC,
        o_values: Union[Order, None] = Order.ASC,
        meta_type: Union[MetadataType, None] = None,
    ):
        meta_type = self._parse_arg_meta_type(meta_type)
        if meta_type == MetadataType.FRONTMATTER:
            self.frontmatter.order(k=k, o_keys=o_keys, o_values=o_values)
        elif meta_type == MetadataType.INLINE:
            self.inline.order(k=k, o_keys=o_keys, o_values=o_values)
        elif meta_type == MetadataType.ALL:
            self.frontmatter.order(k=k, o_keys=o_keys, o_values=o_values)
            self.inline.order(k=k, o_keys=o_keys, o_values=o_values)
        else:
            raise ValueError(f"Unsupported value for argument meta_type: {meta_type}")

    def move(
        self,
        k: Union[str, list[str], None] = None,
        fr: Union[MetadataType, None] = None,
        to: Union[MetadataType, None] = None,
    ):
        if k is None:
            for k2 in CONFIG.cfg["fields"]:
                if "default_meta" in CONFIG.cfg["fields"][k2]:
                    default_meta = MetadataType.get_from_str(
                        CONFIG.cfg["fields"][k2]["default_meta"]
                    )
                    m_to = (
                        self.frontmatter
                        if default_meta == MetadataType.FRONTMATTER
                        else self.inline
                    )
                    m_from = (
                        self.frontmatter
                        if default_meta == MetadataType.INLINE
                        else self.inline
                    )
                    m_to.add(k=k2, l=m_from.metadata[k2])
                    m_from.remove(k=k2)
            return

        assert (fr is not None) and (to is not None), "args 'fr' and 'to' should be set"
        if isinstance(k, str):
            k = [k]
        m_from = self.inline if fr == MetadataType.INLINE else self.frontmatter
        m_to = self.inline if to == MetadataType.INLINE else self.frontmatter

        for k2 in k:
            if k2 in m_from.metadata:
                m_to.add(k=k2, l=m_from.metadata[k2])
                m_from.remove(k=k2)


def return_metaclass(
    meta_type: MetadataType,
) -> Union[Type[Metadata], Type[NoteMetadata], None]:
    if meta_type == MetadataType.FRONTMATTER:
        return Frontmatter
    elif meta_type == MetadataType.INLINE:
        return InlineMetadata
    elif meta_type == MetadataType.ALL:
        return NoteMetadata
    else:
        return None
        # raise NotImplementedError(f'no metadata class implemented of type "{meta_type}"')