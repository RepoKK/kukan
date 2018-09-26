from abc import ABC, abstractmethod
from lxml import html
import requests
import re
import html2text
import kukan.jautils as jau


class DefinitionWordBase(ABC):
    subclasses = {}
    word_link_regexp = None
    word_base_link = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.subclasses[cls.__name__] = (cls, cls.word_link_regexp)

    @classmethod
    def from_link(cls, link):
        for cl, rx in DefinitionWordBase.subclasses.values():
            if re.match(rx, link):
                return cl(link=link)

    @classmethod
    def from_word(cls, word):
        def_obj = None
        for cl in ['DefinitionKanjipedia', 'DefinitionGoo']:
            o = cls.subclasses[cl][0](word)
            definition, yomi, candidates = o.get_definition()
            if definition or yomi or candidates:
                def_obj = o
                break
        return def_obj

    def __init__(self, word=None, link=None):
        self.word = word
        self.link = link
        self.definition_page = None
        self.candidates = []
        self.definition = ''
        self.yomi = ''

    @abstractmethod
    def parse_def(self):
        pass

    @abstractmethod
    def search_def(self):
        pass

    def _get_page_from_link(self):
        page = requests.get(self.word_base_link + self.link)
        self.definition_page = html.fromstring(page.content.decode('utf-8'))

    def get_definition(self):
        if self.definition and self.yomi:
            return self.definition, self.yomi, []
        if not self.definition and not self.yomi and self.candidates:
            return '', '', self.candidates

        res = '', '', []
        if not self.link:
            self.search_def()
        else:
            self._get_page_from_link()

        if self.definition_page:
            self.parse_def()
            res = self.definition, self.yomi, []
        elif self.candidates:
            res = '', '', self.candidates

        return res


class DefinitionKanjipedia(DefinitionWordBase):
    word_link_regexp = r'/kotoba/\d{10}'
    word_base_link = 'http://www.kanjipedia.jp/'

    def search_def(self):
        link = 'http://www.kanjipedia.jp/search?k={}&wt=1&sk=perfect'.format(self.word)
        page = requests.get(link)

        try:
            target = html.fromstring(page.content.decode('utf-8')).xpath('/html/body/div[1]/div[2]/ul[2]/li/a')
            if len(target) > 1:
                self.candidates = [{'word': self.word + ' ' + t.getchildren()[-1].text,
                                    'link': t.get('href')} for t in target]
            else:
                self.link = target[0].get('href')
                self._get_page_from_link()

        except IndexError:
            pass

    def parse_def(self):
        pg = self.definition_page
        try:
            self.yomi = pg.xpath('/html/body/div[1]/div[2]/div[1]/div/p[2]/text()')[0].translate(jau.hir2kat)
            self.yomi = self.yomi.replace('－', '')
            for i, p in enumerate(pg.xpath('//*[@id="kotobaExplanationSection"]/p')):
                text = html.tostring(p, encoding='unicode')
                text = re.sub(r'<span>(.*?)</span>', r'**【\1】**　', text, re.MULTILINE)
                h = html2text.HTML2Text()
                h.ignore_links = True
                text = re.sub(r'<img.[^,>]+ alt="">', r'=>　', text, re.MULTILINE)
                text = h.handle(re.sub(r'<img.*? alt="(.*?)">', r'**【\1】**　', text, re.MULTILINE))
                if i == 0:
                    text = text.translate({ord('①') + i: '\n\n{}. '.format(1 + i) for i in range(20)})
                self.definition += text
            self.definition = self.definition.strip()
        except IndexError:
                pass

        return self.definition and self.yomi


class DefinitionGoo(DefinitionWordBase):
    word_link_regexp = r'/jn/\d+/meaning/m1u/.+/'
    word_base_link = 'https://dictionary.goo.ne.jp'

    def search_def(self):
        link = 'https://dictionary.goo.ne.jp/srch/jn/{}/m1u/'.format(self.word)
        page = requests.get(link)

        tree = html.fromstring(page.content)
        if len(tree.xpath('//*[@id="NR-main-in"]/section/div/div[2]/div')) == 1:
            self.definition_page = tree
        else:
            for block in tree.xpath('//dt[@class="title search-ttl-a"]'):
                if block.getparent().getparent().get('href')[0:3] == '/jn':
                    self.candidates.append({'word': block.text, 'link': block.getparent().getparent().get('href')})

    def parse_def(self):
        tree = self.definition_page

        block = tree.xpath('//*[@id="NR-main-in"]/section/div/div[2]/div')
        text = html.tostring(block[0], encoding='unicode')
        yomi = tree.xpath('//*[@id="NR-main-in"]/section/div/div[1]/h1/text()')[0]
        yomi = yomi[0:yomi.index('【')].replace('‐', '')
        yomi = yomi.translate(jau.hir2kat)
        yomi = yomi.replace('・', '')
        yomi = re.sub('〔.*〕', '', yomi)

        if text != '':
            h = html2text.HTML2Text()
            h.ignore_links = True
            text = text.replace('<ol', '<ul')
            text = h.handle(text)
            text = re.sub(r' {2}\* \*\*(\d*)\*\*',
                          lambda match: match.group(1).translate(jau.digit_ful2half) + '. ',
                          text)
            text = re.sub(r'__「(.*)の全ての意味を見る\n\n', '', text)

            self.definition = text
            self.yomi = yomi

        return self.definition and self.yomi
