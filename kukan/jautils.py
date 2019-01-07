import re
from janome.tokenizer import Tokenizer
from multiprocessing.connection import Client

from django.conf import settings

katakana_chart = ('ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノ'
                  'ハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヽヾ')
hiragana_chart = ('ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねの'
                  'はばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖゝゞ')

punctuation_chart = '。、・'
alphabet_lower_chart = 'abcdefghijklmnopqrstuvwxyz'
alphabet_upper_chart = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

fullwidth_digit_chart = '０１２３４５６７８９'
halfwidth_digit_chart = '0123456789'

hir2kat = str.maketrans(hiragana_chart, katakana_chart)
hir2nul = dict.fromkeys(map(ord, hiragana_chart), None)
kat2hir = str.maketrans(katakana_chart, hiragana_chart)

digit_ful2half = str.maketrans(fullwidth_digit_chart, halfwidth_digit_chart)


class JpnText:
    """
    New class to handle Japanese text with optional Furigana.

    Furigana format is [KANJI|FURIGANA|f]
    """
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

        def __init__(self, origin, furigana=None):
            self.origin = origin
            self.furigana = furigana.translate(kat2hir) if furigana else None

        def furigana_none(self):
            return self.origin

        def furigana_bracket(self):
            return '[{}|{}|f]'.format(self.origin, self.furigana) if self.furigana else self.origin

        def furigana_ruby(self):
            return '<ruby>{}<rt>{}</rt></ruby>'.format(
                self.origin, self.furigana) if self.furigana else self.origin

        def furigana_simple(self):
            return ' {}[{}]'.format(
                self.origin, self.furigana) if self.furigana else self.origin

        def hiragana(self):
            return self.furigana or self.origin.translate(kat2hir)

        @classmethod
        def get_sub_token(cls, origin, furigana_raw):
            """
            Given a text and its corresponding reading, return a list of up to 3 TextItem with the non-kanji text pre
            and post kanji separated.
            An Exception is raised is the reading do not match

            :param origin: the original test (for instance 'お試し')
            :param furigana_raw: the reading (for instance 'おためし')
            :return: List of TextToken ([お], [試|ため], [し])
            """

            token_list = []
            furigana = furigana_raw.translate(kat2hir)

            sentinel_text = 'sentinel'
            kanji_pattern = '[一-龥]'
            if re.search(kanji_pattern, origin):
                split_token = re.split(u'({}+)'.format(kanji_pattern), '{0}{1}{0}'.format(sentinel_text, origin))

                pre_kanji = split_token[0][len(sentinel_text):] if split_token[0] != sentinel_text else ''
                post_kanji = split_token[-1][:-len(sentinel_text)] if split_token[-1] != sentinel_text else ''

                kanji = origin[len(pre_kanji):-len(post_kanji) or None]
                kana = furigana[len(pre_kanji):-len(post_kanji) or None]

                if not all([furigana.startswith(pre_kanji.translate(kat2hir)),
                            furigana.endswith(post_kanji.translate(kat2hir)),
                            kanji, kana]):
                    raise ValueError('origin [{}] does not match furigana [{}]'.format(origin, furigana))

                if pre_kanji:
                    token_list.append(cls(pre_kanji))
                token_list.append(cls(kanji, kana))
                if post_kanji:
                    token_list.append(cls(post_kanji))
            else:
                if origin.translate(kat2hir) != furigana and origin not in katakana_chart:
                    raise ValueError('origin [{}] does not match furigana [{}]'.format(origin, furigana))
                token_list = [cls(origin)]

            return token_list

    def __init__(self, text, token_list, expected_yomi=None):
        self.token_list = token_list
        self.text = text or self.furigana('none')
        self.expected_yomi = expected_yomi.translate(kat2hir) if expected_yomi else None
        self._furigana_errors = []
        self._check_furigana()

    @classmethod
    def from_text(cls, text, expected_yomi=None):
        token_list = []

        for tok in cls.tokenizer.tokenize(text):
                token_list.extend(cls.TextToken.get_sub_token(tok.surface, tok.reading))

        return cls(text, token_list=token_list, expected_yomi=expected_yomi)

    @classmethod
    def from_ruby(cls, text):
        token_list = []
        pattern_all = r'(<ruby>.+?</ruby>)'
        pattern_sub = r'<ruby>(.+?)<rt>(.*?)</rt></ruby>'
        for item in re.split(pattern_all, text):
            if not item:
                pass
            elif item[:6] == '<ruby>' and item[-7:] == '</ruby>':
                match_obj = re.match(pattern_sub, item)
                token_list.extend(cls.TextToken.get_sub_token(match_obj[1], match_obj[2]))
            else:
                token_list.append(cls.TextToken(item))

        return cls(text, token_list=token_list)

    @classmethod
    def from_furigana_format(cls, furigana_format, text=None, expected_yomi=None):
        token_list = []
        pattern_all = r'(\[.+?\|.+?\|f\])'
        pattern_sub = r'\[(.+?)\|(.+?)\|f\]'
        for item in re.split(pattern_all, furigana_format):
            if not item:
                pass
            elif item[:1] == '[' and item[-1:] == ']':
                match_obj = re.match(pattern_sub, item)
                token_list.extend(cls.TextToken.get_sub_token(match_obj[1], match_obj[2]))
            else:
                token_list.append(cls.TextToken(item))

        return cls(text, token_list=token_list, expected_yomi=expected_yomi)

    def furigana(self, kind='bracket', exclude=None):
        """
        Return the Japanese text with its furigana

        :param kind: The type of furigana, possible value:
            bracket: '[漢字|かんじ|f] - the 'native' form of the class
            ruby: '<ruby>漢字<rt>かんじ</rt></ruby>'
            none: '漢字' (the initial text, no furigana)
            simple: '漢字[かんじ]' - understood by Anki, space between blocks
        :param exclude: list of words to exclude from the
        :return: The text with the furigana
        """
        exclusion_list = exclude or []
        return ''.join([getattr(t, 'furigana_' + (kind if t.origin not in exclusion_list else 'none'))()
                        for t in self.token_list]).strip()

    def hiragana(self):
        """
        Return the word converted to hiragana (no kanji)
        :return: String
        """
        return ''.join([t.hiragana() for t in self.token_list])

    def _check_furigana(self):
        self._furigana_errors = []
        reconverted = self.furigana('none')
        if self.text != reconverted:
            self._furigana_errors.append('元の文章を復元出来ない: 「{}」'.format(reconverted))
        if self.expected_yomi:
            if self.hiragana() != self.expected_yomi:
                self._furigana_errors.append('推測振り仮名と元の読み方が合致しない')

    def get_furigana_errors(self):
        return self._furigana_errors
