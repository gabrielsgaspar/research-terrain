# Codebook: what a Pix work plan says the money is for

Decision 0018. Gabriel approves this codebook by merging it. It is the only
instruction a labelling model receives, with the texts; its SHA-256 is stored
in `data/reference/pix_object_labels.yaml`. Changing a word of it means
relabelling.

## The task

Each text is the "Detalhamento do Objeto" of one work plan of a Pix amendment
(transferência especial): what a town hall declared it would do with the
money. Texts are upper-cased and cut at 600 characters. For each text, give:

1. **One class** (below): the object that takes most of the money, as far as
   the text says. If the text lists several objects, pick the one it names
   first or describes at most length, unless a value or a word ("principal",
   "maior parte") says otherwise. Use MISTO only when the text lists three or
   more unrelated objects and none dominates.
2. **A specificity** of 0, 1 or 2 (below).

Judge only the text. Do not guess what is behind it.

## Classes

| Class | What it covers |
| --- | --- |
| `OBRA_VIARIA` | Roads and urban infrastructure on the ground: paving, asphalt, roads, bridges, drainage, sidewalks. |
| `OBRA_PREDIAL` | Building, renovating or equipping public buildings and spaces: squares, sports courts, schools, health posts, markets, street lighting. |
| `MAQUINAS` | Buying vehicles, machines and equipment, whatever the sector: tractors, trucks, buses, ambulances. |
| `SAUDE` | Health services and running costs: medicines, exams, procedures, health staff, the health fund's costs. |
| `EDUC_SOCIAL` | Education, social assistance, farming support, sport and culture programmes that are neither events nor works. |
| `EVENTOS` | Shows, festivities, fairs, tourism promotion. |
| `CUSTEIO_ADMIN` | The town hall's general running costs: payroll, debts, fuel, upkeep, consultancies, software, "gestão municipal". |
| `VAGO` | No object can be identified. |
| `MISTO` | Three or more unrelated objects, none dominant. |

### Words that point to each class

- `OBRA_VIARIA`: PAVIMENTAÇÃO, PAVIMENTAÇÃO ASFÁLTICA, RECAPEAMENTO, ASFALTO,
  CBUQ, TSD, CALÇAMENTO, BLOQUETES, PARALELEPÍPEDOS, POLIÉDRICAS, ESTRADAS
  VICINAIS, ESTRADAS RURAIS, RECUPERAÇÃO DE ESTRADAS, CASCALHAMENTO,
  ENCASCALHAMENTO, PONTE, BUEIRO, GALERIA, DRENAGEM, MICRODRENAGEM, MEIO-FIO,
  SARJETA, CALÇADAS, PASSEIO, CICLOVIA, ACESSIBILIDADE nas vias, SINALIZAÇÃO
  VIÁRIA, INFRAESTRUTURA URBANA (when it is paving or drainage).
- `OBRA_PREDIAL`: CONSTRUÇÃO, REFORMA, AMPLIAÇÃO, REVITALIZAÇÃO, ADEQUAÇÃO or
  EQUIPAR of a public building or space: PRAÇA, QUADRA (POLIESPORTIVA,
  COBERTA), GINÁSIO, CAMPO DE FUTEBOL, ESCOLA, CRECHE, UBS, POSTO DE SAÚDE,
  UNIDADE BÁSICA, HOSPITAL (the building), MERCADO, FEIRA COBERTA (the
  building), CENTRO COMUNITÁRIO, CEMITÉRIO, MURO, ACADEMIA AO AR LIVRE,
  PARQUE INFANTIL, ILUMINAÇÃO PÚBLICA, LUMINÁRIAS LED, PRÉDIO DA PREFEITURA,
  MOBILIÁRIO for a public building.
- `MAQUINAS`: AQUISIÇÃO DE VEÍCULO, CAMINHÃO, CAMINHÃO-PIPA, CAÇAMBA,
  RETROESCAVADEIRA, PÁ CARREGADEIRA, MOTONIVELADORA, PATROL, ESCAVADEIRA,
  TRATOR, IMPLEMENTOS AGRÍCOLAS, GRADE ARADORA, ÔNIBUS, MICRO-ÔNIBUS, VAN,
  AMBULÂNCIA, MÁQUINAS E EQUIPAMENTOS, EQUIPAMENTOS (any sector, bought).
- `SAUDE`: CUSTEIO DA SAÚDE, ATENÇÃO BÁSICA, ATENÇÃO ESPECIALIZADA,
  MEDICAMENTOS, INSUMOS, MATERIAL HOSPITALAR, EXAMES, CONSULTAS, CIRURGIAS,
  PROCEDIMENTOS, PROFISSIONAIS DE SAÚDE, FUNDO MUNICIPAL DE SAÚDE (its
  costs), HOSPITAL (its services or costs).
- `EDUC_SOCIAL`: MANUTENÇÃO DO ENSINO, MATERIAL ESCOLAR, MERENDA, TRANSPORTE
  ESCOLAR (the service), UNIFORMES, ASSISTÊNCIA SOCIAL, CRAS, CREAS, CESTAS
  BÁSICAS, PROGRAMAS SOCIAIS, APOIO À AGRICULTURA FAMILIAR, SEMENTES, MUDAS,
  CALCÁRIO, HORAS-MÁQUINA for farmers, ASSISTÊNCIA TÉCNICA RURAL, ESCOLINHAS
  DE ESPORTE, PROJETOS CULTURAIS, OFICINAS, BANDA DE MÚSICA.
- `EVENTOS`: SHOWS, FESTA, FESTIVIDADES, FESTEJOS, ANIVERSÁRIO DA CIDADE,
  CARNAVAL, SÃO JOÃO, FESTAS JUNINAS, RÉVEILLON, EXPOSIÇÃO AGROPECUÁRIA,
  FEIRA (the event), RODEIO, EVENTOS, PROMOÇÃO DO TURISMO, CONTRATAÇÃO DE
  ATRAÇÕES ARTÍSTICAS, PALCO, SOM E ILUMINAÇÃO for an event.
- `CUSTEIO_ADMIN`: FOLHA DE PAGAMENTO, PAGAMENTO DE PESSOAL, ENCARGOS,
  DÍVIDAS, PRECATÓRIOS, PARCELAMENTOS, COMBUSTÍVEL, MANUTENÇÃO DA FROTA,
  MANUTENÇÃO DE PRÉDIOS (upkeep, not a renovation), LIMPEZA URBANA, COLETA DE
  LIXO, ENERGIA, ÁGUA, TELEFONE, INTERNET, ASSESSORIA, CONSULTORIA, SOFTWARE,
  SISTEMAS, MATERIAL DE EXPEDIENTE, GESTÃO MUNICIPAL, MANUTENÇÃO DA MÁQUINA
  PÚBLICA, CUSTEIO DA ADMINISTRAÇÃO, DESPESAS CORRENTES (with no sector).
- `VAGO`: ATENDER ÀS NECESSIDADES DO MUNICÍPIO, INVESTIMENTOS DIVERSOS,
  CONFORME PLANO DE TRABALHO, APLICAÇÃO EM AÇÕES DE INTERESSE DO MUNICÍPIO,
  TRANSFERÊNCIA ESPECIAL, EMENDA PARLAMENTAR with no object, a text that only
  repeats a budget code, an amount, a law or a programme name.

## Decision rules and borderline cases

1. **Works against equipment.** Building, renovating or paving is a work
   (OBRA_*). Buying a vehicle, machine or equipment is MAQUINAS, also for a
   school, a health post or farming. Equipping a building (furniture, air
   conditioning, kitchen for a school) is OBRA_PREDIAL; a vehicle or a heavy
   machine is always MAQUINAS.
2. **Roads against buildings.** Streets, roads, bridges, drainage and
   sidewalks are OBRA_VIARIA. Squares, courts, buildings and street lighting
   are OBRA_PREDIAL. "INFRAESTRUTURA URBANA" with no detail is OBRA_VIARIA;
   with a square or a building named, OBRA_PREDIAL.
3. **Health.** Building or renovating a health post or hospital is
   OBRA_PREDIAL; an ambulance is MAQUINAS; everything else for health
   (services, staff, medicines, "custeio", "incremento temporário", the
   health fund) is SAUDE.
4. **Farming.** Tractors and implements are MAQUINAS. Rural roads are
   OBRA_VIARIA. Inputs, technical help, machine hours and programmes for
   farmers are EDUC_SOCIAL.
5. **Sport and culture.** Building a court or a cultural centre is
   OBRA_PREDIAL. A festival, show, party, fair or rodeo is EVENTOS. A
   programme (classes, teams, workshops, a band) is EDUC_SOCIAL.
6. **Running costs.** Running costs of one named sector go to that sector:
   health to SAUDE; education and social assistance to EDUC_SOCIAL. The town
   hall's general costs, or costs with no sector, are CUSTEIO_ADMIN. Upkeep
   ("manutenção", "conservação") of streets or buildings is CUSTEIO_ADMIN;
   a renovation or recovery ("reforma", "recuperação") is a work.
7. **Vague texts.** A sector with no object ("AÇÕES NA ÁREA DA SAÚDE") goes
   to that sector's class with specificity 0. A text that names no sector and
   no object is VAGO. A text that only says "custeio" or "investimento" with
   no sector is VAGO; "custeio da administração" or "gestão" is
   CUSTEIO_ADMIN.
8. **Several objects.** One or two objects: the one that takes most of the
   money (rule in "The task"). Three or more unrelated objects with none
   dominant: MISTO. Several streets to pave are one object (OBRA_VIARIA).
9. **Status words.** "LEGADO", "PLANO DE AÇÃO", numbers of laws, processes
   or programmes carry no object; ignore them and classify the rest.

## Specificity

| Value | Meaning | Example (made up) |
| --- | --- | --- |
| 0 | No identifiable object: VAGO, or a sector with no object. | "AÇÕES DE SAÚDE NO MUNICÍPIO" |
| 1 | A type of object, with no place and no quantity. | "PAVIMENTAÇÃO DE VIAS URBANAS" |
| 2 | An object with a place (a street, a district, a named building) or a quantity (metres, units, a model). | "PAVIMENTAÇÃO DE 1.200 M² NA RUA DAS FLORES" |

VAGO always has specificity 0. MISTO has 1 unless each object has a place or
a quantity (2).

## Groups for analysis

For the analysis only; they do not change how a text is labelled.

- visible: OBRA_VIARIA, OBRA_PREDIAL, MAQUINAS, EVENTOS;
- services: SAUDE, EDUC_SOCIAL;
- fungible: CUSTEIO_ADMIN, VAGO, MISTO, and Pix payments with no work plan.

## Answer format

The texts come as a JSON list of objects `{"id": <number>, "text": <text>}`.
Answer with one JSON list and nothing else, one object per text, in the same
order: `{"id": <number>, "class": "<CLASS>", "specificity": <0, 1 or 2>}`.
