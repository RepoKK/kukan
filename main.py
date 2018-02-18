import CKanjiDeck


# MAIN
root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
importFileName = root_dir + r'AnkiExport\漢字.txt'
outputFileName = root_dir + r'AnkiImport\DeckKanji.txt'


deck = CKanjiDeck.CKanjiDeck()
deck.CreateDeckFromAnkiFile(importFileName)

deck.ProcessJitenon()

print(deck["帥"].get_json())

print(deck["帥"]["Jouyou Grade"])

#print(deck.GetNbOfKanjiWithGaiYomi())
#print(deck.GetNbOfReading())
