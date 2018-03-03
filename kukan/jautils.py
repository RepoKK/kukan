katakana_chart = ("ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノ"
                  "ハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヽヾ")
hiragana_chart = ("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねの"
                  "はばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖゝゞ")

fullwidth_digit_chart = ("０１２３４５６７８９")
halfwidth_digit_chart = ("0123456789")

hir2kat = str.maketrans(hiragana_chart, katakana_chart)
kat2hir = str.maketrans(katakana_chart, hiragana_chart)

digit_ful2half = str.maketrans(fullwidth_digit_chart, halfwidth_digit_chart)
