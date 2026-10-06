"""Build this feature's contribution to the shared RAG corpus.

Writes rag-server/corpus/LeHoaLong_goals_budgeting_knowledge.txt. The corpus
file itself is the artefact and is committed; this script records how it was
derived, and regenerates it reproducibly if a fact is added.

**Why the file is shaped in blocks.** rag_pipeline.chunk_text splits the whole
file's words into consecutive 80-word groups, with no regard for sentences or
paragraphs. A topic that does not begin on a multiple of 80 is therefore
blended into its neighbour's chunk, and a blended chunk matches no question
well. Each block below is padded to an exact multiple of 80 words with further
true facts from its own pool, so every chunk is one topic.

Measured effect on retrieval, against the questions POST
/api/goals/<id>/explain actually asks (see LeHoaLong/docs/pull-requests.md):

    unaligned prose, topics grouped only by order   10/15 key facts retrieved
    blocks aligned to the 80-word window           13/15
    aligned blocks + the embedding fix in PR 4     15/15

The remaining two misses are not fixable from this file. rag_pipeline's
embedding sums all 32 sha256 bytes into dimensions 0..31 of a 256-dimension
vector, so 224 dimensions are always zero and an 80-word chunk is the sum of
~80 random vectors, which converges on noise. Ranking is therefore only
loosely related to word overlap: the chunk defining "behind" shares 12 tokens
with the behind question and ranks 10th, while the chunk that wins shares 6.
PR 4 in that document proposes the three-line fix and measures it.

**Every sentence here is a fact about savings goals and budgeting**, in the
core sets and the pools alike. The pools exist so the *selection* can be
adjusted to land on a chunk boundary, not so that the content can be padded
with anything untrue.

    python LeHoaLong/tools/build_corpus.py          # regenerate and report
    python LeHoaLong/tools/build_corpus.py --check  # verify, write nothing
"""

import sys
from itertools import combinations
from pathlib import Path

# rag-server/ is a shared directory: this script writes exactly one file in
# it, the one this feature owns (see docs/pull-requests.md, PR 5).
CORPUS_FILE = (
    Path(__file__).resolve().parents[2]
    / "rag-server"
    / "corpus"
    / "LeHoaLong_goals_budgeting_knowledge.txt"
)

WINDOW = 80  # rag_pipeline.chunk_text's max_words

BLOCKS = [
    # ---------------------------------------------------------------- goals
    {
        "name": "what a savings goal is",
        "core": [
            "A savings goal is a named amount of money that a person intends to save by a chosen target date.",
            "A savings goal has a target amount, a target date, and a priority of high, medium or low.",
            "The target amount of a savings goal is the total amount the person intends to have saved when the goal is complete.",
            "The target date of a savings goal is the date by which the person intends to have saved the target amount.",
        ],
        "pool": [
            "A contribution is money recorded against a savings goal.",
            "The amount saved to date for a savings goal is the total of the contributions recorded against that goal.",
            "The remaining amount of a savings goal is its target amount less the amount saved to date.",
            "A savings goal with no contributions recorded has an amount saved to date of zero.",
            "A person may hold several savings goals at the same time.",
            "A savings goal belongs to one person.",
            "Every savings goal has a name.",
            "A target date is a calendar date.",
            "A savings goal has one target amount.",
            "Saving money toward a goal is called contributing.",
            "A target amount is an amount of money.",
        ],
    },
    # --------------------------------------------------------------- status
    {
        "name": "the status of a savings goal",
        "core": [
            "A savings goal is active while the person is still saving for it.",
            "A savings goal is achieved once the amount saved to date has reached the target amount.",
            "A paused savings goal is one the person has stopped contributing to for now.",
            "An abandoned savings goal is one the person has decided not to continue.",
            "A savings goal that is achieved needs no further contributions, and the monthly amount it required becomes available for the remaining savings goals to use.",
        ],
        "pool": [
            "An active savings goal is one the person is currently contributing to.",
            "A savings goal that is paused can be made active again later.",
            "Only an active savings goal requires a contribution each month.",
            "A savings goal that is abandoned requires no further contributions.",
            "A status describes where a savings goal stands.",
            "An achieved savings goal is complete.",
            "A paused savings goal is not being contributed to.",
            "An abandoned savings goal is closed.",
            "A status can change over time.",
        ],
    },
    # ------------------------------------------------------- prioritisation
    {
        "name": "prioritising competing goals",
        "core": [
            "Savings goals are prioritised when a person has more goals than money to put toward them.",
            "Prioritising savings goals means deciding which goals receive contributions first when the amount available to save is limited.",
            "A savings goal with high priority receives contributions before a goal with lower priority when the monthly budget cannot cover both.",
        ],
        "pool": [
            "Savings goals are commonly prioritised by how soon the target date falls and by how important the goal is to the person.",
            "A savings goal with a target date that falls sooner is usually prioritised above a savings goal with a later target date.",
            "An emergency fund is usually prioritised above discretionary savings goals such as travel, entertainment or a new device.",
            "Competing savings goals are goals that each require a contribution from the same monthly budget.",
            "Lowering the priority of a savings goal means it receives contributions after the others.",
            "A priority is high, medium or low.",
            "Priorities can be changed at any time.",
            "Prioritising means ordering goals by importance.",
        ],
    },
    # ------------------------------------------------------- emergency fund
    {
        "name": "emergency funds",
        "core": [
            "An emergency fund is a savings goal held for unexpected expenses such as medical costs, urgent repairs or a loss of income.",
            "An emergency fund is commonly set to a target amount equal to three to six months of essential living expenses.",
        ],
        "pool": [
            "An emergency fund is kept available to withdraw rather than locked away, because the expenses it covers are not planned.",
            "Contributing to an emergency fund before other savings goals reduces the chance that an unexpected expense interrupts those other goals.",
            "A person who has no emergency fund may have to stop contributing to other savings goals when an unexpected expense arrives.",
            "An emergency fund is rebuilt after it has been spent.",
            "The size of an emergency fund depends on the person's essential living expenses.",
            "An emergency fund is a savings goal.",
            "Unexpected expenses cannot be planned for.",
            "An emergency fund protects other savings goals.",
        ],
    },
    # ----------------------------------------------------- target-date plan
    {
        "name": "target date planning and instalments",
        "core": [
            "Target date planning divides the remaining amount of a savings goal into instalments that fall due before the target date.",
            "An instalment is one scheduled contribution toward a savings goal, with its own amount and its own due date.",
            "A contribution schedule is the ordered list of instalments planned for a savings goal.",
            "The monthly instalment for a savings goal is its remaining amount divided by the number of months remaining before the target date.",
        ],
        "pool": [
            "A savings goal with a nearer target date requires a larger monthly instalment than the same savings goal with a later target date.",
            "Moving the target date of a savings goal later reduces the monthly instalment the goal requires.",
            "Reducing the target amount of a savings goal also reduces the monthly instalment the goal requires.",
            "Scheduling contributions on the same day each month, such as a payday, makes a savings goal easier to keep to.",
            "The instalments of a contribution schedule add up to the remaining amount of the savings goal.",
            "Instalments are ordered by their due date.",
            "A due date is a calendar date.",
            "Planning a savings goal produces a contribution schedule.",
        ],
    },
    # ------------------------------------------------- one chunk per status
    #
    # Three blocks of exactly one chunk each, rather than one block of three
    # definitions. The /explain question for a goal that is behind asks both
    # what "behind" means and what to do about it, so the definition and the
    # action have to share a chunk -- in a two-chunk block they land either
    # side of the boundary and the chunk holding the definition matches
    # nothing the question says.
    {
        "name": "a goal that is on track",
        "core": [
            "A savings goal is on track when the amount saved to date matches the amount the plan expected by that date.",
            "A savings goal that is on track needs no change to its monthly contributions before the target date.",
        ],
        "pool": [
            "A savings goal that is on track will reach its target amount by its target date if the contributions continue.",
            "A variance small enough to fall within a tolerance is treated as on track.",
            "A variance of zero means a savings goal is on track.",
            "Contributions continue unchanged while a savings goal is on track.",
            "On track means the plan is being met.",
            "A savings goal that is on track needs no replanning.",
            "Being on track is the expected state of a savings goal.",
        ],
    },
    {
        "name": "a goal that is behind",
        "core": [
            "A savings goal is behind when the amount contributed to date is less than the amount the plan expected by that date.",
            "A savings goal that is behind needs larger monthly contributions to catch up before the target date.",
        ],
        "pool": [
            "Monthly contributions are adjusted to catch up on a savings goal that is behind by dividing the remaining amount by the months that remain.",
            "A negative variance means a savings goal is behind.",
            "Behind means less has been saved than the plan expected.",
            "A savings goal that is behind has fallen short of the amount expected to date.",
            "The amount a savings goal is behind by is its variance.",
            "A savings goal that is behind can still reach its target amount by its target date.",
            "Being behind on a savings goal is measured against the plan, not against the target amount.",
        ],
    },
    {
        "name": "a goal that is ahead",
        "core": [
            "A savings goal is ahead when the amount contributed to date is more than the amount the plan expected by that date.",
            "A savings goal that is ahead can continue with smaller monthly contributions before the target date.",
        ],
        "pool": [
            "When a savings goal is ahead, the target date can be brought forward or the surplus can be directed to another savings goal.",
            "A positive variance means a savings goal is ahead.",
            "Ahead means more has been saved than the plan expected.",
            "A savings goal that is ahead may reach its target amount before its target date.",
            "Being ahead on a savings goal creates room in the monthly budget.",
            "When a savings goal is ahead, contributions can be reduced.",
            "The amount a savings goal is ahead by is its variance.",
        ],
    },
    {
        "name": "measuring progress and variance",
        "core": [
            "Progress on a savings goal is measured by comparing the amount saved to date against the amount the contribution schedule expected by that date.",
            "The amount expected to date for a savings goal is the total of the instalments that have already fallen due.",
            "The variance of a savings goal is the amount saved to date less the amount expected to date.",
        ],
        "pool": [
            "A savings goal with no contribution schedule has nothing expected to date.",
            "A variance is an amount of money.",
            "Progress is measured against the plan.",
            "A variance can be negative, zero or positive.",
            "The variance of a savings goal changes as contributions are recorded.",
        ],
    },
    # ------------------------------------------------------------ catch up
    {
        "name": "catching up and replanning",
        "core": [
            "When a savings goal is behind, the remaining amount can be spread across the instalments that remain so the goal still reaches its target amount by the target date.",
            "Monthly contributions are adjusted to catch up on a savings goal by dividing the remaining amount by the months that remain.",
            "Catching up on a savings goal that is behind requires larger contributions, a later target date, or a smaller target amount.",
        ],
        "pool": [
            "Spreading the remaining amount of a savings goal across fewer remaining months increases the monthly instalment the goal requires.",
            "When a savings goal is ahead, contributions can be reduced, the target date can be brought forward, or the surplus can be directed to another savings goal.",
            "Recalculating the instalments of a savings goal after it has drifted from its plan is called replanning.",
            "Replanning a savings goal leaves completed instalments unchanged and recalculates only the instalments that are still pending.",
            "A savings goal that falls further behind requires a larger increase in its monthly contributions to catch up.",
            "Catching up means returning to the plan.",
            "Replanning recalculates the pending instalments.",
            "Contributions are adjusted when a goal is behind.",
        ],
    },
    # -------------------------------------------------------------- budget
    {
        "name": "the monthly budget and allocation",
        "core": [
            "A monthly budget is the amount a person has available to put toward savings goals each month.",
            "Budget allocation across competing savings goals means dividing the monthly budget between goals that each require a monthly instalment.",
            "When the total monthly commitment is more than the monthly budget, the options are to pause a savings goal, lower a target amount, move a target date later, or increase the monthly budget.",
        ],
        "pool": [
            "The total monthly commitment of a person's savings goals is the sum of the monthly instalments required by each active savings goal.",
            "A person is over budget when the total monthly commitment of their active savings goals is more than their monthly budget.",
            "A person is within budget when the total monthly commitment of their active savings goals is less than or equal to their monthly budget.",
            "A savings goal that is paused releases the monthly instalment it required for the other savings goals to use.",
            "A monthly budget that is increased allows a larger total monthly commitment.",
            "A monthly budget is set by the person.",
            "Allocation divides a monthly budget between savings goals.",
            "A commitment is an amount required each month.",
        ],
    },
    # --------------------------------------------------------------- bills
    {
        "name": "recurring bills and what is left to save",
        "core": [
            "A recurring bill is a payment that falls due on a repeating schedule, such as electricity, internet, insurance, a mobile plan or a subscription.",
            "The amount available to save each month is the monthly budget less the amount already committed to recurring bills and to other savings goals.",
            "Money already committed to recurring bills is not available to contribute to savings goals.",
        ],
        "pool": [
            "The monthly cost of a recurring bill is the amount of that bill converted to a monthly equivalent.",
            "A bill that is paid fortnightly has a monthly cost larger than its fortnightly amount, and a bill paid yearly has a monthly cost smaller than its yearly amount.",
            "A savings plan that does not account for recurring bills can require more each month than the person actually has available to save.",
            "A person whose recurring bills and savings goals together exceed their monthly budget is over committed.",
            "Reducing or cancelling a recurring bill increases the amount available to save each month.",
            "The shortfall is the amount by which a required monthly instalment exceeds the amount available to save.",
            "A subscription is a recurring bill.",
            "Recurring bills are paid every month.",
            "Bills reduce the amount available to save.",
        ],
    },
]


def words(sentences):
    return sum(len(sentence.split()) for sentence in sentences)


def solve(block):
    """Pick pool sentences so the block is an exact multiple of the window.

    Prefers the fewest additions, and among equal counts the earliest pool
    entries, so the result is deterministic and the most useful facts win.
    """
    core_words = words(block["core"])
    target = ((core_words - 1) // WINDOW + 1) * WINDOW

    while target <= core_words + words(block["pool"]):
        for size in range(0, len(block["pool"]) + 1):
            for extras in combinations(block["pool"], size):
                if core_words + words(extras) == target:
                    return block["core"] + list(extras), target
        target += WINDOW
    return None, target


def main():
    chosen = []
    report = []
    for block in BLOCKS:
        sentences, target = solve(block)
        if sentences is None:
            report.append(f"UNSOLVED {block['name']}: cannot reach {target} words")
            continue
        report.append(
            f"{words(sentences):>4} words ({words(sentences) // WINDOW} chunk(s))  {block['name']}"
        )
        chosen.append(sentences)

    print("\n".join(report))

    offset = 0
    for sentences in chosen:
        assert offset % WINDOW == 0, f"block starts mid-chunk at word {offset}"
        offset += words(sentences)

    body = "\n\n\n".join("\n\n".join(sentences) for sentences in chosen) + "\n"
    total = len(body.split())
    print(f"\ntotal {total} words -> {total / WINDOW:.2f} chunks, aligned: {total % WINDOW == 0}")

    if "--check" in sys.argv:
        current = CORPUS_FILE.read_text(encoding="utf-8") if CORPUS_FILE.is_file() else ""
        if current == body:
            print(f"{CORPUS_FILE.name} matches this script")
            return 0
        print(f"{CORPUS_FILE.name} DIFFERS from this script -- run without --check to regenerate")
        return 1

    CORPUS_FILE.write_text(body, encoding="utf-8")
    print(f"written to {CORPUS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
