"""Стартовые справочники: группы препаратов и действующие вещества (МНН) для ветеринарии.

Это заготовка, а не истина: клиника правит названия, добавляет своё и сама привязывает
вещества к препаратам прайса. Повторный запуск ничего не дублирует.
"""

from django.conf import settings
from django.db import migrations

# Группа → вещества: (название, латинское, другие названия).
REFERENCE = {
    "Антибиотики": [
        ("амоксициллин", "Amoxicillinum", ""), ("клавулановая кислота", "Acidum clavulanicum", ""),
        ("ампициллин", "Ampicillinum", ""), ("цефтриаксон", "Ceftriaxonum", ""),
        ("цефазолин", "Cefazolinum", ""), ("цефалексин", "Cefalexinum", ""),
        ("цефовецин", "Cefovecinum", ""), ("цефтиофур", "Ceftiofurum", ""),
        ("энрофлоксацин", "Enrofloxacinum", ""), ("марбофлоксацин", "Marbofloxacinum", ""),
        ("ципрофлоксацин", "Ciprofloxacinum", ""), ("прадофлоксацин", "Pradofloxacinum", ""),
        ("доксициклин", "Doxycyclinum", ""), ("окситетрациклин", "Oxytetracyclinum", ""),
        ("гентамицин", "Gentamicinum", ""), ("амикацин", "Amikacinum", ""),
        ("неомицин", "Neomycinum", ""), ("тобрамицин", "Tobramycinum", ""),
        ("линкомицин", "Lincomycinum", ""), ("клиндамицин", "Clindamycinum", ""),
        ("тилозин", "Tylosinum", ""), ("азитромицин", "Azithromycinum", ""),
        ("спирамицин", "Spiramycinum", ""), ("метронидазол", "Metronidazolum", ""),
        ("сульфаметоксазол", "Sulfamethoxazolum", ""), ("триметоприм", "Trimethoprimum", ""),
    ],
    "Противогельминтные": [
        ("празиквантел", "Praziquantelum", ""), ("пирантел", "Pyrantelum", ""),
        ("фенбендазол", "Fenbendazolum", ""), ("фебантел", "Febantelum", ""),
        ("альбендазол", "Albendazolum", ""), ("левамизол", "Levamisolum", ""),
        ("мильбемицина оксим", "Milbemycini oximum", "мильбемицин"),
        ("ивермектин", "Ivermectinum", ""), ("моксидектин", "Moxidectinum", ""),
        ("селамектин", "Selamectinum", ""), ("эмодепсид", "Emodepsidum", ""),
    ],
    "От блох и клещей": [
        ("фипронил", "Fipronilum", ""), ("имидаклоприд", "Imidaclopridum", ""),
        ("перметрин", "Permethrinum", ""), ("флураланер", "Fluralanerum", ""),
        ("афоксоланер", "Afoxolanerum", ""), ("сароланер", "Sarolanerum", ""),
        ("лотиланер", "Lotilanerum", ""), ("пирипроксифен", "Pyriproxyfenum", ""),
        ("метопрен", "Methoprenum", "S-метопрен"), ("спиносад", "Spinosadum", ""),
    ],
    "Противопротозойные": [
        ("имидокарб", "Imidocarbum", ""), ("диминазен", "Diminazenum", ""),
        ("толтразурил", "Toltrazurilum", ""),
    ],
    "Противогрибковые": [
        ("итраконазол", "Itraconazolum", ""), ("кетоконазол", "Ketoconazolum", ""),
        ("тербинафин", "Terbinafinum", ""), ("клотримазол", "Clotrimazolum", ""),
        ("миконазол", "Miconazolum", ""), ("энилконазол", "Enilconazolum", ""),
    ],
    "Противовирусные и иммуномодуляторы": [
        ("интерферон", "Interferonum", ""),
        ("меглюмина акридонацетат", "Meglumini acridonacetas", ""),
        ("полипренилфосфат натрия", "", ""),
    ],
    "Противовоспалительные (НПВС)": [
        ("мелоксикам", "Meloxicamum", ""), ("карпрофен", "Carprofenum", ""),
        ("робенакоксиб", "Robenacoxibum", ""), ("фирококсиб", "Firocoxibum", ""),
        ("кетопрофен", "Ketoprofenum", ""), ("толфенамовая кислота", "Acidum tolfenamicum", ""),
        ("метамизол натрия", "Metamizolum natricum", "анальгин"),
    ],
    "Опиоидные анальгетики": [
        ("буторфанол", "Butorphanolum", ""), ("трамадол", "Tramadolum", ""),
        ("бупренорфин", "Buprenorphinum", ""),
    ],
    "Глюкокортикоиды": [
        ("дексаметазон", "Dexamethasonum", ""), ("преднизолон", "Prednisolonum", ""),
        ("метилпреднизолон", "Methylprednisolonum", ""), ("триамцинолон", "Triamcinolonum", ""),
        ("бетаметазон", "Betamethasonum", ""), ("гидрокортизон", "Hydrocortisonum", ""),
    ],
    "Анестетики (общий наркоз)": [
        ("пропофол", "Propofolum", ""), ("тилетамин", "Tiletaminum", ""),
        ("золазепам", "Zolazepamum", ""), ("кетамин", "Ketaminum", ""),
        ("изофлуран", "Isofluranum", ""), ("севофлуран", "Sevofluranum", ""),
        ("альфаксалон", "Alfaxalonum", ""),
    ],
    "Местные анестетики": [
        ("лидокаин", "Lidocainum", ""), ("бупивакаин", "Bupivacainum", ""),
        ("прокаин", "Procainum", "новокаин"),
    ],
    "Седативные": [
        ("ксилазин", "Xylazinum", ""), ("медетомидин", "Medetomidinum", ""),
        ("дексмедетомидин", "Dexmedetomidinum", ""), ("ацепромазин", "Acepromazinum", ""),
        ("диазепам", "Diazepamum", ""), ("мидазолам", "Midazolamum", ""),
    ],
    "Антагонисты седации": [("атипамезол", "Atipamezolum", "")],
    "Противорвотные": [
        ("маропитант", "Maropitantum", ""), ("метоклопрамид", "Metoclopramidum", ""),
        ("ондансетрон", "Ondansetronum", ""),
    ],
    "Спазмолитики": [
        ("дротаверин", "Drotaverinum", ""), ("папаверин", "Papaverinum", ""),
    ],
    "Гастропротекторы": [
        ("омепразол", "Omeprazolum", ""), ("пантопразол", "Pantoprazolum", ""),
        ("фамотидин", "Famotidinum", ""), ("сукральфат", "Sucralfatum", ""),
    ],
    "Гепатопротекторы": [
        ("адеметионин", "Ademetioninum", ""),
        ("урсодезоксихолевая кислота", "Acidum ursodeoxycholicum", ""),
        ("силимарин", "Silymarinum", ""),
    ],
    "Слабительные": [
        ("лактулоза", "Lactulosum", ""), ("вазелиновое масло", "Paraffinum liquidum", ""),
    ],
    "Сорбенты и противодиарейные": [
        ("смектит диоктаэдрический", "Smectitum dioctaedricum", ""),
        ("активированный уголь", "Carbo activatus", ""), ("лоперамид", "Loperamidum", ""),
    ],
    "Мочегонные": [
        ("фуросемид", "Furosemidum", ""), ("торасемид", "Torasemidum", ""),
        ("спиронолактон", "Spironolactonum", ""),
    ],
    "Сердечные": [
        ("пимобендан", "Pimobendanum", ""), ("дигоксин", "Digoxinum", ""),
        ("амлодипин", "Amlodipinum", ""), ("атенолол", "Atenololum", ""),
        ("эналаприл", "Enalaprilum", ""), ("беназеприл", "Benazeprilum", ""),
        ("рамиприл", "Ramiprilum", ""), ("телмисартан", "Telmisartanum", ""),
    ],
    "Противоаллергические": [
        ("хлоропирамин", "Chloropyraminum", ""), ("дифенгидрамин", "Diphenhydraminum", "димедрол"),
        ("клемастин", "Clemastinum", ""), ("цетиризин", "Cetirizinum", ""),
        ("оклацитиниб", "Oclacitinibum", ""),
    ],
    "Иммунодепрессанты": [("циклоспорин", "Ciclosporinum", "")],
    "Гормональные (репродукция)": [
        ("окситоцин", "Oxytocinum", ""), ("каберголин", "Cabergolinum", ""),
        ("аглепристон", "Aglepristonum", ""), ("делорелин", "Deslorelinum", "деслорелин"),
    ],
    "Эндокринные": [
        ("инсулин", "Insulinum", ""), ("левотироксин", "Levothyroxinum", ""),
        ("тиамазол", "Thiamazolum", ""), ("трилостан", "Trilostanum", ""),
    ],
    "Противосудорожные": [
        ("фенобарбитал", "Phenobarbitalum", ""), ("леветирацетам", "Levetiracetamum", ""),
        ("габапентин", "Gabapentinum", ""), ("прегабалин", "Pregabalinum", ""),
    ],
    "Успокоительные (поведение)": [
        ("тразодон", "Trazodonum", ""), ("флуоксетин", "Fluoxetinum", ""),
    ],
    "Витамины": [
        ("цианокобаламин", "Cyanocobalaminum", "витамин B12"), ("тиамин", "Thiaminum", "витамин B1"),
        ("аскорбиновая кислота", "Acidum ascorbinicum", "витамин C"),
        ("фитоменадион", "Phytomenadionum", "витамин K"),
    ],
    "Инфузионные растворы": [
        ("натрия хлорид", "Natrii chloridum", "физраствор"),
        ("раствор Рингера", "Solutio Ringeri", "Рингер"), ("декстроза", "Dextrosum", "глюкоза"),
    ],
    "Кровоостанавливающие": [
        ("этамзилат", "Etamsylatum", ""), ("транексамовая кислота", "Acidum tranexamicum", ""),
    ],
    "Антикоагулянты": [("гепарин натрия", "Heparinum natricum", "гепарин")],
    "Антисептики": [
        ("хлоргексидин", "Chlorhexidinum", ""), ("повидон-йод", "Povidonum-iodum", ""),
        ("перекись водорода", "Hydrogenii peroxidum", ""),
    ],
    "Бронхолитики и муколитики": [
        ("аминофиллин", "Aminophyllinum", "эуфиллин"), ("амброксол", "Ambroxolum", ""),
        ("ацетилцистеин", "Acetylcysteinum", ""),
    ],
    "Хондропротекторы": [
        ("глюкозамин", "Glucosaminum", ""), ("хондроитина сульфат", "Chondroitini sulfas", "хондроитин"),
    ],
    "Противоопухолевые": [
        ("винкристин", "Vincristinum", ""), ("доксорубицин", "Doxorubicinum", ""),
        ("циклофосфамид", "Cyclophosphamidum", ""),
    ],
    "Неотложная помощь": [
        ("эпинефрин", "Epinephrinum", "адреналин"), ("атропин", "Atropinum", ""),
    ],
    "Для эвтаназии": [("пентобарбитал", "Pentobarbitalum", "")],
    # Группы без стартовых веществ — для препаратов, которые удобнее найти по назначению.
    "Вакцины": [],
    "Сыворотки и иммуноглобулины": [],
    "Пробиотики и ферменты": [],
    "Глазные": [],
    "Ушные": [],
    "Наружные (кожа)": [],
}


def create(apps, schema_editor):
    DrugGroup = apps.get_model("catalog", "DrugGroup")
    Substance = apps.get_model("catalog", "Substance")
    node = {"node_id": settings.NODE_ID}
    for group_name, substances in REFERENCE.items():
        group, _ = DrugGroup.objects.get_or_create(name=group_name, defaults=node)
        for name, latin, synonyms in substances:
            Substance.objects.get_or_create(
                name=name, defaults={**node, "latin_name": latin, "synonyms": synonyms, "group": group}
            )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0008_drug_substances_groups")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
