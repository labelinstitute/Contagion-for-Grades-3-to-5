from otree.api import *
import csv
import os
import json
import random

doc = """
CONTAGION (Spec v10 + practice)
- 4 practice periods (no points earned)
- 6 blocks, 10 rounds/block  => 60 regular periods
- Total rounds = 64
- Block start assignments from CSV: node_id, neighbors_list, x,y, risk_type, initial_germ
- Actions: IN(+1), OUT(+3); dead: NO CHOICE, 0 payoff; revived at each block start
- Germ dynamics:
    IN  -> germ = max(germ-1, 0) w.p. 1
    OUT -> gain +1 germ w.p. p_gain = lambda * (#infected neighbors who chose OUT)/degree
- Display prob (Decision): p_display = lambda * (#infected neighbors)/degree  (assume neighbors choose OUT)
- Infection source: any alive neighbor with germ>=1 (blue infected OR red sick)
- Death (red only, sick only): p_die = min(0.90, 0.02*germ)
- Decision page shows network + current health; dead players see network but cannot choose
- PeriodFeedback shows same health, and greys nodes who chose IN
- Block points: block_points resets each block and accumulates within block; players keep points earned before dying
"""


# -----------------------
# CONSTANTS
# -----------------------
class C(BaseConstants):
    NAME_IN_URL = "contagion"
    PLAYERS_PER_GROUP = 10

    PRACTICE_ROUNDS = 4
    NUM_BLOCKS = 6 # was 6
    ROUNDS_PER_BLOCK = 10
    NUM_ROUNDS = PRACTICE_ROUNDS + NUM_BLOCKS * ROUNDS_PER_BLOCK  # 64

    # infection intensity (λ)
    LAMBDA = 0.75

    # Death probability for red-type when sick
    DIE_SLOPE = 0.2
    DIE_CAP = 0.90

    ASSIGNMENTS_CSV = "block_assignments.csv"

    CANVAS_W = 560
    CANVAS_H = 560
    PAD = 60

    TIMER_SECONDS = 6


# -----------------------
# MODELS
# -----------------------
class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


class Player(BasePlayer):
    # Block-assigned (overwritten at each block start)
    node_id = models.IntegerField()
    neighbors_json = models.LongStringField()
    pos_x = models.FloatField()
    pos_y = models.FloatField()
    risk_type = models.StringField()

    # evolving state
    germ = models.IntegerField(initial=0)
    alive = models.BooleanField(initial=True)

    # snapshot for visuals this round
    germ_start = models.IntegerField(initial=0)
    alive_start = models.BooleanField(initial=True)

    # decision
    action = models.StringField(
        choices=[("in", "IN"), ("out", "OUT"), ("nochoice", "NO CHOICE")],
        initial="nochoice",
    )

    # block points (reset each block)
    block_points = models.IntegerField(initial=0)

    # debug/prob tracking
    p_display = models.FloatField(initial=0)
    p_gain = models.FloatField(initial=0)
    p_die = models.FloatField(initial=0)

    # realized germ change for UI (-1/0/+1)
    germ_delta = models.IntegerField(initial=0)

    # death memory for BlockFeedback
    died_this_block = models.BooleanField(initial=False)
    points_at_death = models.IntegerField(initial=0)
    germ_at_death = models.IntegerField(initial=0)

    # =====================
    # Decision behavior data (NO UI effect)
    # =====================
    rt_first_click_ms = models.FloatField(initial=0)
    used_popup = models.BooleanField(initial=False)
    click_count = models.IntegerField(initial=0)


# ======================================================================
# HELPERS — block management
# ======================================================================
def is_practice_round(round_number: int) -> bool:
    return round_number <= C.PRACTICE_ROUNDS


def current_block(round_number: int) -> int:
    """
    Practice rounds => block 0 (special; not in CSV)
    Regular rounds  => blocks 1..NUM_BLOCKS
    """
    if is_practice_round(round_number):
        return 0
    adjusted = round_number - C.PRACTICE_ROUNDS  # starts at 1
    return (adjusted - 1) // C.ROUNDS_PER_BLOCK + 1


def is_block_start(round_number: int) -> bool:
    """
    Round 1 = start of practice
    Round (PRACTICE_ROUNDS + 1) = start of block 1
    Then every 10 rounds = new block start
    """
    if round_number == 1:
        return True
    if is_practice_round(round_number):
        return False
    adjusted = round_number - C.PRACTICE_ROUNDS
    return (adjusted - 1) % C.ROUNDS_PER_BLOCK == 0


# ======================================================================
# CSV LOADER (cached)
# ======================================================================
_ASSIGNMENTS = None


def parse_neighbors(s: str):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def load_block_assignments():
    global _ASSIGNMENTS
    if _ASSIGNMENTS is not None:
        return _ASSIGNMENTS

    path = os.path.join(os.path.dirname(__file__), C.ASSIGNMENTS_CSV)
    assignments = {}

    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            block = int(row["round"])
            node_id = int(row["node_id"])

            assignments.setdefault(block, {})[node_id] = dict(
                neighbors=parse_neighbors(row["neighbors_list"]),
                x=float(row["position_x"]),
                y=float(row["position_y"]),
                risk_type=(row["risk_type"] or "").strip().lower(),
                initial_germ=int(row["initial_germ"]),
            )

    for b in range(1, C.NUM_BLOCKS + 1):
        if b not in assignments:
            raise ValueError(f"CSV missing block {b} (round={b})")
        for nid in range(1, C.PLAYERS_PER_GROUP + 1):
            if nid not in assignments[b]:
                raise ValueError(f"CSV missing node_id {nid} in block {b}")

    _ASSIGNMENTS = assignments
    return _ASSIGNMENTS


def assign_practice_state(subsession: Subsession):
    """
    Practice uses the same network/assignments as block 1,
    but points are blocked elsewhere.
    """
    assignments = load_block_assignments()
    block = 1

    for p in subsession.get_players():
        nid = p.id_in_group
        a = assignments[block][nid]

        p.node_id = nid
        p.neighbors_json = json.dumps(a["neighbors"])
        p.pos_x = a["x"]
        p.pos_y = a["y"]
        p.risk_type = a["risk_type"]

        p.germ = a["initial_germ"]
        p.alive = True

        p.action = "nochoice"
        p.block_points = 0

        p.p_display = 0
        p.p_gain = 0
        p.p_die = 0

        p.germ_delta = 0

        p.died_this_block = False
        p.points_at_death = 0
        p.germ_at_death = 0

        p.germ_start = p.germ
        p.alive_start = p.alive


def assign_block_state(subsession: Subsession):
    """
    Apply CSV assignments + revival at block start.
    Also reset death memory each block.
    """
    assignments = load_block_assignments()
    block = current_block(subsession.round_number)

    for p in subsession.get_players():
        nid = p.id_in_group
        a = assignments[block][nid]

        # fixed within the block (from CSV)
        p.node_id = nid
        p.neighbors_json = json.dumps(a["neighbors"])
        p.pos_x = a["x"]
        p.pos_y = a["y"]
        p.risk_type = a["risk_type"]

        # state reset at block start
        p.germ = a["initial_germ"]
        p.alive = True

        # decision reset
        p.action = "nochoice"

        # block points reset
        p.block_points = 0

        # debug reset
        p.p_display = 0
        p.p_gain = 0
        p.p_die = 0

        # reset realized delta
        p.germ_delta = 0

        # reset death memory at block start
        p.died_this_block = False
        p.points_at_death = 0
        p.germ_at_death = 0

        # snapshot
        p.germ_start = p.germ
        p.alive_start = p.alive


def carry_forward_within_block(subsession: Subsession):
    """For non-block-start rounds: copy last round's UPDATED state into this round."""
    for p in subsession.get_players():
        prev = p.in_round(subsession.round_number - 1)

        # fixed within block
        p.node_id = prev.node_id
        p.neighbors_json = prev.neighbors_json
        p.pos_x = prev.pos_x
        p.pos_y = prev.pos_y
        p.risk_type = prev.risk_type

        # updated each round
        p.germ = prev.germ
        p.alive = prev.alive

        # carry block points within block
        p.block_points = prev.block_points

        # per-round reset for choice + debug
        p.action = "nochoice"
        p.p_display = 0
        p.p_gain = 0
        p.p_die = 0

        # reset realized delta each round
        p.germ_delta = 0

        # carry death memory within block
        p.died_this_block = prev.died_this_block
        p.points_at_death = prev.points_at_death
        p.germ_at_death = prev.germ_at_death

        # snapshot
        p.germ_start = p.germ
        p.alive_start = p.alive


# ======================================================================
# HELPERS — health / probabilities
# ======================================================================
def neighbors_of(player: Player):
    ids = json.loads(player.neighbors_json or "[]")
    return [player.group.get_player_by_id(int(nid)) for nid in ids]


def cap01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def is_infectious_start(p: Player) -> bool:
    return bool(p.alive_start) and int(p.germ_start) >= 1


def p_display(player: Player, lam: float) -> float:
    neigh = neighbors_of(player)
    d = len(neigh)
    if d == 0:
        return 0.0
    infected = sum(1 for n in neigh if is_infectious_start(n))
    return cap01(lam * infected / d)


def p_gain(player: Player, lam: float) -> float:
    neigh = neighbors_of(player)

    # neighbors who chose OUT
    out_neighbors = [
        n for n in neigh
        if n.action == "out"
    ]

    d_out = len(out_neighbors)
    if d_out == 0:
        return 0.0

    # among those, how many are contagious?
    infected_out = sum(
        1 for n in out_neighbors
        if is_infectious_start(n)
    )

    return cap01(lam * infected_out / d_out)


def p_die_from_germ(g: int) -> float:
    return cap01(min(C.DIE_CAP, C.DIE_SLOPE * int(g)))


# ======================================================================
# CORE DYNAMICS — apply updates
# ======================================================================
def get_action_safe(p: Player):
    a = p.field_maybe_none("action")
    if not a:
        return None
    a = a.strip().lower()
    return a if a in ["in", "out"] else None

'''
def apply_germ_update(player: Player):
    old = int(player.germ_start)

    if not player.alive_start:
        player.germ = old
        player.germ_delta = 0
        return

    action = get_action_safe(player)

    if action == "in":
        new = max(old - 1, 0)
        player.germ = new
        player.germ_delta = new - old
        return

    if action == "out":
        pg = p_gain(player, C.LAMBDA)
        player.p_gain = pg

        got_infected = (random.random() < pg)
        new = old + 1 if got_infected else old
        player.germ = new
        player.germ_delta = new - old
        return

    player.germ = old
    player.germ_delta = 0

'''

def apply_germ_update(player: Player):
    old = int(player.germ_start)

    if not player.alive_start:
        player.germ = old
        player.germ_delta = 0
        return

    action = get_action_safe(player)

    if action == "in":
        new = max(old - 1, 0)
        player.germ = new
        player.germ_delta = new - old
        return

    if action == "out":
        pg = float(player.p_gain or 0)     # ✅ already computed for everyone
        got_infected = (random.random() < pg)
        new = old + 1 if got_infected else old
        player.germ = new
        player.germ_delta = new - old
        return

    player.germ = old
    player.germ_delta = 0


'''
def apply_death(player: Player):
    """
    If death happens, store block totals at time of death.
    """
    if not player.alive_start:
        return
    if player.risk_type != "red":
        return
    if int(player.germ) < 1:
        return

    pd = p_die_from_germ(int(player.germ))
    player.p_die = pd

    if random.random() < pd:
        player.alive = False
        player.died_this_block = True
        player.germ_at_death = int(player.germ)
        
 '''
def apply_death(player: Player): # When it is probabilistic
    """
    Death only if:
    - alive at start of period
    - red type
    - chose OUT
    - germ after germ update >= 3
    """
    if not player.alive_start:
        return
    if player.risk_type != "red":
        return
    if player.action != "out":
        return
    if int(player.germ) < 1:
        return

    pd = p_die_from_germ(int(player.germ))
    player.p_die = pd

    if random.random() < pd:
        player.alive = False
        player.died_this_block = True
        player.germ_at_death = int(player.germ)

'''
def apply_death(player: Player): # When death is DETERMINISTIC AT 3 GERMS
    """
    Deterministic death:
    - alive at start of period
    - red type
    - chose OUT
    - germ after germ update == 3
    """
    if not player.alive_start:
        return
    if player.risk_type != "red":
        return
    if player.action != "out":
        return
    if int(player.germ) != 3:
        return

    # deterministic death
    player.p_die = 1.0
    player.alive = False
    player.died_this_block = True
    player.germ_at_death = 3
'''

def apply_block_points(player: Player):
    if not player.alive_start:
        return

    # ensure payoff is never None
    if player.payoff is None:
        player.payoff = 0

    # practice: no earnings
    if is_practice_round(player.round_number):
        return

    if player.action == "out":
        player.block_points += 3
        player.payoff += 3
    elif player.action == "in":
        player.block_points += 1
        player.payoff += 1


'''
def end_of_round_updates(group: Group):
    for p in group.get_players():
        apply_germ_update(p)

    # points should be awarded even if they die after acting (practice excluded)
    for p in group.get_players():
        apply_block_points(p)

    # now apply death, and if they died, capture points-at-death
    for p in group.get_players():
        was_alive_before = p.alive  # after germ update + points
        apply_death(p)
        if was_alive_before and (p.alive is False):
            p.points_at_death = int(p.block_points)
'''

def end_of_round_updates(group: Group):

    # ✅ compute p_gain for everyone (based on neighbors' actions)
    for p in group.get_players():
        p.p_gain = p_gain(p, C.LAMBDA)

    for p in group.get_players():
        apply_germ_update(p)

    for p in group.get_players():
        apply_block_points(p)

    for p in group.get_players():
        was_alive_before = p.alive
        apply_death(p)
        if was_alive_before and (p.alive is False):
            p.points_at_death = int(p.block_points)

# ======================================================================
# HELPER FUNCTIONS - Network
# ======================================================================
def normalize_positions(pos_dict, width=C.CANVAS_W, height=C.CANVAS_H, pad=C.PAD):
    if not pos_dict:
        return {}

    xs = [v[0] for v in pos_dict.values()]
    ys = [v[1] for v in pos_dict.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = max(1e-9, max_x - min_x)
    span_y = max(1e-9, max_y - min_y)

    out = {}
    for node, (x, y) in pos_dict.items():
        nx = pad + (x - min_x) * (width - 2 * pad) / span_x
        ny = pad + (y - min_y) * (height - 2 * pad) / span_y
        out[node] = (nx, ny)
    return out


# ======================================================================
# SESSION INIT
# ======================================================================
def creating_session(subsession: Subsession):
    if subsession.round_number == 1:
        assign_practice_state(subsession)


# ======================================================================
# PAGES
# ======================================================================
class Welcome(Page):
    """
    Initial welcome page shown only in round 1.
    Admin must advance all players to start the game.
    """
    @staticmethod
    def is_displayed(player: Player):
        return player.round_number == 1


class EndPractice(Page):
    """
    End of practice page shown after round 4,
    before the real game starts in round 5.
    """
    @staticmethod
    def is_displayed(player: Player):
        return player.round_number == C.PRACTICE_ROUNDS


class HoldBeforeDecision(WaitPage):
    """
    At every round:
    - block start => load + revive + reset block_points
    - otherwise  => carry forward state within the block
    """
    @staticmethod
    def after_all_players_arrive(group: Group):
        subsession = group.subsession
        if is_block_start(subsession.round_number):
            if current_block(subsession.round_number) == 0:
                assign_practice_state(subsession)
            else:
                assign_block_state(subsession)
        else:
            carry_forward_within_block(subsession)


class NetworkWaitPage(WaitPage):
    pass


class Decision(Page):
    form_model = "player"

    @staticmethod
    def get_form_fields(player: Player):
        # Always record these (even if dead)
        fields = ["rt_first_click_ms", "used_popup", "click_count"]

        # Only alive players can choose action
        if player.alive_start:
            fields = ["action"] + fields

        return fields

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        if not player.alive_start:
            player.action = "nochoice"
            return

        a = (player.field_maybe_none("action") or "").strip().lower()
        player.action = a if a in ["in", "out"] else "nochoice"

    @staticmethod
    def vars_for_template(player: Player):
        pd = p_display(player, C.LAMBDA)
        player.p_display = pd

        # ===== Practice + Block/Day logic =====
        practice_rounds = 4
        is_practice = is_practice_round(player.round_number)

        if player.round_number <= practice_rounds:
            # Practice: show Practice Day 1-4
            day_in_block = player.round_number
            block_number = 0
        else:
            # Real game starts at round 5 -> Block 1, Day 1
            real_round = player.round_number - practice_rounds
            day_in_block = ((real_round - 1) % 10) + 1
            block_number = ((real_round - 1) // 10) + 1

        positions = {}
        states = {}
        actions = {}

        for p in player.group.get_players():
            positions[str(p.node_id)] = dict(x=p.pos_x, y=p.pos_y)

            if not p.alive_start:
                health = "dead"
            elif int(p.germ_start) == 0:
                health = "healthy"
            else:
                health = "infected" if p.risk_type == "blue" else "sick"

            states[p.node_id] = dict(
                alive=p.alive_start,
                risk_type=p.risk_type,
                germ=int(p.germ_start),
                health=health,
            )

            actions[p.node_id] = p.action

        edges = []
        for p in player.group.get_players():
            for nid_str in json.loads(p.neighbors_json or "[]"):
                edges.append(dict(a=p.node_id, b=int(nid_str)))

        return dict(
            round=player.round_number,

            # Keep your original block_num if you still use it elsewhere
            block_num=current_block(player.round_number),

            # New display variables (practice-aware)
            is_practice=is_practice,
            day_in_block=day_in_block,
            block_number=block_number,

            positions=positions,
            my_neighbors=json.loads(player.neighbors_json or "[]"),
            edges=edges,
            states=states,
            actions=actions,
            p_display=round(pd * 100, 1),
            me_alive=player.alive_start,
            germ=int(player.germ_start),
            risk_type=player.risk_type,
            timer=C.TIMER_SECONDS,
            canvas_w=C.CANVAS_W,
            canvas_h=C.CANVAS_H,
            pad=C.PAD,
        )


class ResultsWaitPage(WaitPage):
    @staticmethod
    def after_all_players_arrive(group: Group):
        end_of_round_updates(group)


class PeriodFeedback(Page):
    @staticmethod
    def vars_for_template(player: Player):
        raw_pos = {str(p.node_id): (p.pos_x, p.pos_y) for p in player.group.get_players()}
        norm = normalize_positions(raw_pos, width=C.CANVAS_W, height=C.CANVAS_H, pad=C.PAD)
        positions = {k: dict(x=v[0], y=v[1]) for k, v in norm.items()}

        states = {}
        actions = {}
        dim = {}

        for p in player.group.get_players():
            if not p.alive_start:
                health = "dead"
            elif int(p.germ_start) == 0:
                health = "healthy"
            else:
                health = "infected" if p.risk_type == "blue" else "sick"

            states[p.node_id] = dict(
                alive=p.alive_start,
                risk_type=p.risk_type,
                germ=int(p.germ_start),
                health=health,
            )

            actions[p.node_id] = p.action
            dim[p.node_id] = bool(p.alive_start and p.action == "in")

        edges = []
        for p in player.group.get_players():
            for nid_str in json.loads(p.neighbors_json or "[]"):
                edges.append(dict(a=p.node_id, b=int(nid_str)))

        germ_change = int(player.germ_delta)

        pg_percent = round((player.p_gain or 0) * 100, 1)  # feedback screen

        return dict(
            round=player.round_number,
            block_num=current_block(player.round_number),
            is_practice=is_practice_round(player.round_number),
            positions=positions,
            my_neighbors=json.loads(player.neighbors_json or "[]"),
            edges=edges,
            states=states,
            actions=actions,
            dim=dim,
            canvas_w=C.CANVAS_W,
            canvas_h=C.CANVAS_H,
            block_points=player.block_points,
            my_action=player.action,
            my_alive_now=player.alive,
            my_risk=player.risk_type,
            my_germ_new=int(player.germ),
            germ_change=germ_change,
            p_gain=pg_percent,
            show_pie=(player.action == "out" and player.alive_start),  # ✅ Added this line
        )

class BlockFeedback(Page):
    @staticmethod
    def is_displayed(player: Player):
        if is_practice_round(player.round_number):
            return False
        adjusted = player.round_number - C.PRACTICE_ROUNDS
        return adjusted % C.ROUNDS_PER_BLOCK == 0

    @staticmethod
    def vars_for_template(player: Player):
        alive_end = bool(player.alive)

        # If died earlier in block, show stored death totals
        if player.died_this_block and (not alive_end):
            show_points = int(player.points_at_death)
            show_germ = int(player.germ_at_death)
            status_line = "You did not survive in this block."
        else:
            show_points = int(player.block_points)
            show_germ = int(player.germ)
            status_line = f"End of Block {current_block(player.round_number)}"

        return dict(
            block_num=current_block(player.round_number),
            status_line=status_line,
            show_points=show_points,
            show_germ=show_germ,
            alive_end=alive_end,
            died_this_block=bool(player.died_this_block),
            my_risk=player.risk_type,
        )


class End(Page):
    @staticmethod
    def is_displayed(player: Player):
        return player.round_number == C.NUM_ROUNDS

    @staticmethod
    def vars_for_template(player: Player):
        total_points = sum((p.payoff or 0) for p in player.in_all_rounds())

        if not player.alive:
            final_health = "dead"
        elif int(player.germ) == 0:
            final_health = "healthy"
        else:
            final_health = "infected" if player.risk_type == "blue" else "sick"

        return dict(
            total=int(total_points),
            alive=bool(player.alive),
            final_germ=int(player.germ),
            final_health=final_health,
        )


page_sequence = [
    Welcome,
    HoldBeforeDecision,
    NetworkWaitPage,
    Decision,
    ResultsWaitPage,
    PeriodFeedback,
    EndPractice,
    BlockFeedback,
    End,
]
