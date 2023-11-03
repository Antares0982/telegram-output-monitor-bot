"""
This file is copied from RBQ project. DO NOT EDIT.
"""


from typing import List


def force_longtext_split(txt: List[str]) -> List[str]:
    counting = 0
    i = 0
    ans: List[str] = []
    sep_len = 0
    while i < len(txt):
        if counting + len(txt[i]) < 1024 - sep_len:
            counting += len(txt[i])
            sep_len = 1
            i += 1
        else:
            if i == 0:
                # 超长行，被迫分割
                super_long_line = txt[0]
                _end = min(1000, len(super_long_line))
                part = super_long_line[:_end]
                txt[0] = super_long_line[_end:]
                ans.append(part)
                continue
            else:
                ans.append("\n".join(txt[:i]))
                txt = txt[i:]
                i = 0
                sep_len = 0
                counting = 0
    if len(txt) > 0:
        ans.append("\n".join(txt))
    return ans


def longtext_split(txt: str) -> List[str]:
    if len(txt) < 1024:
        return [txt]
    txts = txt.split("\n")
    ans: List[str] = []
    # search for ``` of markdown block
    dotsss_start = -1
    dotsss_end = -1
    for i in range(len(txts)):
        if txts[i].startswith("```"):
            if dotsss_start == -1:
                dotsss_start = i
            else:
                dotsss_end = i
                break
    if dotsss_start != -1 and dotsss_end != -1:
        if dotsss_start == 0 and dotsss_end == len(txts)-1:
            # cannot keep markdown block!!!
            return force_longtext_split(txts)
        parts = txts[:dotsss_start], txts[dotsss_start:dotsss_end+1], txts[dotsss_end+1:]
        for i, part in enumerate(parts):
            if len(part) > 0:
                if i == 0:
                    ans.extend(force_longtext_split(part))
                else:
                    this_text = "\n".join(part)
                    ans.extend(longtext_split(this_text))
        return ans
    #
    return force_longtext_split(txts)
