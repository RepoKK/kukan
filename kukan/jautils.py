import re
from janome.tokenizer import Tokenizer
from multiprocessing.connection import Client

from django.conf import settings

katakana_chart = ("ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノ"
                  "ハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヽヾ")
hiragana_chart = ("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねの"
                  "はばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖゝゞ")

punctuation_chart = ("。、・")
alphabet_lower_chart = ("abcdefghijklmnopqrstuvwxyz")
alphabet_upper_chart = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

fullwidth_digit_chart = ("０１２３４５６７８９")
halfwidth_digit_chart = ("0123456789")

hir2kat = str.maketrans(hiragana_chart, katakana_chart)
hir2nul = dict.fromkeys(map(ord, hiragana_chart), None)
kat2hir = str.maketrans(katakana_chart, hiragana_chart)

digit_ful2half = str.maketrans(fullwidth_digit_chart, halfwidth_digit_chart)


class JpText:
    class LightTokenizer:
        """
        Provide an interface to a resident process in prod, and just using directly the Tokenizer in dev

        The Tokenizer is heavy, and having each of the instance of the Apache instantiating it consume too much RAM
        """

        full_tokenizer = Tokenizer() if not hasattr(settings, 'JANOME_PORT') else None

        @classmethod
        def tokenize(cls, text):
            if cls.full_tokenizer:
                res = cls.full_tokenizer.tokenize(text)
            else:
                with Client(('localhost', settings.JANOME_PORT), authkey=settings.JANOME_KEY) as conn:
                    conn.send([text])
                    res = conn.recv()
            return res

    tokenizer = LightTokenizer()

    class TextToken:
        tok_regex = re.compile(r'([一-龥].*?\]| .*?\])')
        kanji_tok_regex = re.compile(r'(^[一-龥].*?)\[(.*)\]')

        def __init__(self, origin, kana=None, is_kanji=False):
            self.origin = origin
            self.kana = kana or self.origin
            self.is_kanji = is_kanji

        def get_simple(self, excluded_token=[]):
            if self.is_kanji and self.origin not in excluded_token:
                res = ' {}[{}]'.format(self.origin, self.kana)
            else:
                res = self.origin
            return res

        def get_html(self):
            if self.is_kanji:
                res = '<ruby>{}<rt>{}</rt></ruby>'.format(self.origin, self.kana)
            else:
                res = self.origin
            return res

        @classmethod
        def from_elem(cls, elem):
            rx_res = cls.kanji_tok_regex.match(elem)
            if rx_res:
                text_token_res = cls(rx_res.groups()[0], rx_res.groups()[1], True)
            else:
                text_token_res = cls(elem, elem, False)
            return text_token_res

        @classmethod
        def from_furigana_text(cls, furigana):
            tok_list = [t.strip() for t in cls.tok_regex.split(furigana) if t]
            return [cls.from_elem(t) for t in tok_list]

    def __init__(self, text, yomi=None, furigana=None, token_list=[]):
        self.text = text
        self.yomi = yomi
        self.token_list = token_list
        # self.furigana = furigana
        self.furigana_errors = []
        if furigana and not token_list:
            self.token_list = self.TextToken.from_furigana_text(furigana)
        self._check_furigana()

    @classmethod
    def from_furigana_text(cls, furigana):
        token_list = cls.TextToken.from_furigana_text(furigana)
        return cls(''.join([t.origin for t in token_list]),
                   token_list=token_list)

    @staticmethod
    def kat2hir(word):
        return word.translate(kat2hir)

    @staticmethod
    def tohensu(origin, kana):
        origin = "".join(origin)
        kana = "".join(kana)
        return origin, kana

    @classmethod
    def kanadelete(cls, origin, kana):
        origin = list(origin)
        kana = list(kana)
        num1 = len(origin)
        num2 = len(kana)
        okurigana = ""
        if origin[num1 - 1] == kana[num2 - 1] and origin[num1 - 2] == kana[num2 - 2]:
            okurigana = origin[num1 - 2] + origin[num1 - 1]
            origin[num1 - 1] = ""
            origin[num1 - 2] = ""
            kana[num2 - 1] = ""
            kana[num2 - 2] = ""
            origin, kana = cls.tohensu(origin, kana)
        elif origin[num1 - 1] == kana[num2 - 1]:
            okurigana = origin[num1 - 1]
            origin[num1 - 1] = ""
            kana[num2 - 1] = ""
            origin = "".join(origin)
            kana = "".join(kana)
        else:
            origin, kana = cls.tohensu(origin, kana)
        return origin, kana, okurigana

    def _check_furigana(self):
        self.furigana_errors = []
        reconverted = ''.join([t.origin for t in self.token_list])
        if not reconverted == self.text:
            self.furigana_errors.append('元の文章を復元出来ない: 「{}」'.format(reconverted))
        if self.yomi:
            if not ''.join([t.kana for t in self.token_list]) == self.kat2hir(self.yomi):
                self.furigana_errors.append('推測振り仮名と元の読み方が合致しない')

    def guess_furigana(self):
        self.token_list = []
        furigana = ''
        furigana_html = ''
        for tok in self.tokenizer.tokenize(self.text):
            origin = tok.surface  # もとの単語を代入
            kana = self.kat2hir(tok.reading)  # 読み仮名を代入
            # 正規表現で漢字と一致するかをチェック
            pattern = "[一-龥]"
            matchOB = re.search(pattern, origin)
            # originが空のとき、漢字以外の時はふりがなを振る必要がないのでそのまま出力する
            if origin != "" and matchOB:
                # 正規表現で「漢字+仮名」かどうかチェック
                matchOB_kanji_kana = re.fullmatch(r'(^[一-龥]+)([\u3041 -\u3093]+)', origin)
                # 正規表現で「仮名+漢字」かどうかチェック
                matchOB_kana_kanji = re.fullmatch(r'(^[\u3041 -\u3093]+)([一-龥]+)', origin)
                # 正規表現で「漢字+仮名」の場合
                if origin != "" and matchOB_kanji_kana:
                    # 漢字を基準に分割
                    origin_split = re.split(u'([一-龥]+)', origin)
                    # 不要な空白を削除
                    origin_split = [x.strip() for x in origin_split if x.strip()]
                    # 「送り仮名」を含んだ「読み仮名」から「送り仮名」を後方一致で削除する
                    kana = kana.rstrip(origin_split[1])
                    self.token_list.append(self.TextToken(origin_split[0], kana, True))
                    self.token_list.append(self.TextToken(origin_split[1]))
                # 正規表現で「仮名+漢字」の場合
                elif origin != "" and matchOB_kana_kanji:
                    # 漢字を基準に分割
                    origin_split = re.split(u'([一-龥]+)', origin)
                    # 不要な空白を削除
                    origin_split = [x.strip() for x in origin_split if x.strip()]
                    # 「行頭の仮名」を含んだ「読み仮名」から「行頭の仮名」を前方一致で削除する
                    kana = kana.lstrip(origin_split[0])
                    self.token_list.append(self.TextToken(origin_split[0]))
                    self.token_list.append(self.TextToken(origin_split[1], kana, True))
                else:
                    origin, kana, okurigana = self.kanadelete(origin, kana)
                    self.token_list.append(self.TextToken(origin, kana, True))
            else:
                self.token_list.append(self.TextToken(origin))

        self._check_furigana()
        return self.get_furigana_simple()

    def get_furigana_errors(self):
        return self.furigana_errors

    def get_furigana_simple(self, excluded_token=[]):
        return ''.join([t.get_simple(excluded_token) for t in self.token_list]).strip()

    def get_furigana_html(self):
        return ''.join([t.get_html() for t in self.token_list])
