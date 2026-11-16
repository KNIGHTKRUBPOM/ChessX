"""ตรวจ business rules แยกจากเครือข่ายและ UI."""

from collections import deque
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from backend import chess_rules as chess, draughts_rules as draughts
from backend import duel_rules as duel, game, hybrid_rules as hybrid, models, rooms


def square(name):
    return (8-int(name[1])) * 8 + ord(name[0]) - ord("a")


def position(turn, pieces, *, mixed=False):
    board = [None] * 64
    for name, side, kind, *extra in pieces:
        index = square(name)
        board[index] = {"side": side, "type": kind, "id": index, **(extra[0] if extra else {})}
    result = chess.empty_state(board, turn)
    result["hybrid"] = mixed
    return result


def piece(state, name):
    return state["board"][square(name)]


def selected(engine, state, origin, target, **extra):
    fr = None if origin is None else square(origin)
    return next(m for m in engine.turn_options(state)["moves"]
                if m.get("from") == fr and m["to"] == square(target)
                and all(m.get(k) == v for k,v in extra.items()))


def plays(engine, state, *turns):
    for origin, target in turns:
        state = engine.play(state, selected(engine, state, origin, target))
    return state


def origins(options):
    return {m.get("from") for m in options["moves"]}


class ChessTests(unittest.TestCase):
    def test_u01_opening_and_piece_lookup(self):
        start=chess.start()
        self.assertEqual((start["turn"],len(start["board"]),len(chess.legal_moves(start))),("w",64,20))
        self.assertEqual(sum(p is not None for p in start["board"]),32)
        for index in (-1,64,None):
            self.assertIsNone(chess.piece_at(start["board"],index))
        self.assertEqual(chess.piece_at(start["board"],63)["type"],"r")

    def test_u02_en_passant_capture_and_expiry(self):
        pos=plays(chess,chess.start(),("e2","e4"),("a7","a6"),("e4","e5"),("d7","d5"))
        before=deepcopy(pos)
        move=selected(chess,pos,"e5","d6")
        self.assertEqual(move["capture"],square("d5"))
        after=chess.play(pos,move)
        self.assertIsNone(piece(after,"d5"))
        self.assertEqual(piece(after,"d6")["side"],"w")
        self.assertEqual(after["reserve"]["b"],1)
        self.assertEqual(pos,before)
        expired=plays(chess,pos,("g1","f3"),("g8","f6"))
        self.assertIsNone(expired["enPassant"])
        self.assertFalse(any(m["from"]==square("e5") and m["to"]==square("d6") for m in chess.legal_moves(expired)))

    def test_u03_both_castles_move_rook(self):
        pos=position("w",[("e1","w","k"),("a1","w","r"),("h1","w","r"),("e8","b","k")])
        for target,rook in [("g1","f1"),("c1","d1")]:
            with self.subTest(target=target):
                after=plays(chess,pos,("e1",target))
                self.assertEqual(piece(after,target)["type"],"k")
                self.assertEqual(piece(after,rook)["type"],"r")
                self.assertTrue(piece(after,rook)["moved"])

    def test_u04_castle_fails_moved_rook_block_or_check(self):
        for blocker in [("f8","b","r"),("e6","b","r"),("h1","w","r",{"moved":True}),("f1","w","n")]:
            with self.subTest(blocker=blocker):
                pos=position("w",[("e1","w","k"),("h1","w","r"),("e8","b","k"),blocker])
                self.assertFalse(any("rookFrom" in m for m in chess.legal_moves(pos)))

    def test_u05_promotion_offers_four_and_preserves_identity_and_skill(self):
        pos=position("w",[("e1","w","k"),("e8","b","k"),("a7","w","p",{"card":"lock"})])
        moves=[m for m in chess.legal_moves(pos) if m["from"]==square("a7") and m["to"]==square("a8")]
        self.assertEqual({m["promote"] for m in moves},{"q","r","b","n"})
        result=chess.play(pos,selected(chess,pos,"a7","a8",promote="n"))
        self.assertEqual(piece(result,"a8"),{"type":"n","side":"w","id":square("a7"),"card":"lock","moved":True})

    def test_u06_detects_attacks_and_pinned_piece(self):
        for kind,location in [("p","d5"),("n","f6"),("r","e7"),("b","h7"),("q","d4"),("h","g6"),("k","f4")]:
            with self.subTest(kind=kind):
                self.assertTrue(chess.in_check(position("w",[("e4","w","k"),(location,"b",kind)])["board"],"w"))
        self.assertFalse(chess.in_check([None]*64,"w"))
        pos=position("w",[("e1","w","k"),("e2","w","r"),("e8","b","r"),("a8","b","k")])
        targets=[m["to"] for m in chess.legal_moves(pos) if m["from"]==square("e2")]
        self.assertTrue(targets)
        self.assertTrue(all(t%8==4 for t in targets))

    def test_u07_opposing_skill_and_friendly_capture(self):
        for card in ("lock","revive","push","friendly"):
            with self.subTest(card=card):
                pos=position("w",[("e1","w","k"),("e8","b","k"),("a1","w","r"),("a7","b","p",{"card":card})])
                after=plays(chess,pos,("a1","a7"))
                self.assertEqual(after["locks"]["w"],square("a1") if card=="lock" else None)
                self.assertEqual(after["pending"],None if card=="lock" else card)
        pos=position("w",[("e1","w","k"),("e8","b","k"),("a1","w","r"),("a2","w","p",{"card":"push"})])
        pos["pending"]="friendly"
        after=plays(chess,pos,("a1","a2"))
        self.assertEqual(after["reserve"]["w"],1)
        self.assertIsNone(after["pending"])

    def test_u08_revival_generates_new_id_and_uses_reserve(self):
        pos=position("w",[("e1","w","k"),("e8","b","k"),("a2","w","p")])
        pos["pending"]="revive"
        self.assertFalse(chess.turn_options(pos)["forced"])
        pos["reserve"]["w"]=1
        self.assertEqual(len(chess.revival_moves(pos)),7)
        after=plays(chess,pos,(None,"b2"))
        self.assertEqual((piece(after,"b2")["id"],after["nextId"],after["reserve"]["w"]),(64,65,0))

    def test_u09_push_locked_pawn_and_sole_check_escape(self):
        start=chess.start()
        start["pending"]="push"
        start["locks"]["w"]=square("d2")
        options=chess.turn_options(start)
        self.assertTrue(options["forced"])
        self.assertEqual(len(options["moves"]),7)
        self.assertNotIn(square("d2"),origins(options))
        self.assertTrue(all(m["from"]-m["to"]==8 for m in options["moves"]))
        pos=position("w",[("a1","w","k"),("a8","b","r"),("c3","b","k")])
        pos["locks"]["w"]=square("a1")
        self.assertEqual(chess.turn_options(pos)["moves"],[{"from":square("a1"),"to":square("b1")}])

    def test_u10_low_level_errors_do_not_change_board(self):
        start=chess.start()
        before=deepcopy(start)
        for move,message in [({"from":32,"to":33},"start on a piece"),
                             ({"from":60,"to":62,"rookFrom":34,"rookTo":61},"requires a rook")]:
            with self.subTest(move=move),self.assertRaisesRegex(ValueError,message):
                chess.moved_board(start,move)
        self.assertEqual(start,before)


class DraughtsTests(unittest.TestCase):
    def test_u11_opening_black_has_seven_moves_on_dark_squares(self):
        pos=draughts.start()
        opts=draughts.turn_options(pos)
        self.assertEqual((pos["turn"],len(opts["moves"]),opts["mustCapture"]),("b",7,False))
        self.assertEqual(sum(p is not None for p in pos["board"]),16)
        self.assertTrue(all((i//8+i%8)%2 for i,p in enumerate(pos["board"]) if p))

    def test_u12_forced_chain_defers_reveal_until_final_capture(self):
        pos=position("w",[("a3","w","p"),("b4","b","p",{"card":"lock"}),("d6","b","p",{"cards":["push"]})])
        before=deepcopy(pos)
        pos["queue"]["w"]=["push"]
        options=draughts.turn_options(pos)
        self.assertTrue(options["mustCapture"])
        self.assertEqual(options["consumed"],0)
        interim=plays(draughts,pos,("a3","c5"))
        self.assertEqual((interim["turn"],interim["chain"]["at"]),("w",square("c5")))
        self.assertIsNone(interim["resolution"])
        self.assertTrue(draughts.turn_options(interim)["mustCapture"])
        final=plays(draughts,interim,("c5","e7"))
        self.assertEqual(final["turn"],"b")
        self.assertIsNone(final["chain"])
        self.assertEqual(final["resolution"]["route"],list(map(square,["a3","c5","e7"])))
        self.assertEqual(final["resolution"]["cards"],["lock","push"])
        self.assertEqual(final["queue"]["b"],["push"])
        self.assertEqual(final["reserve"]["b"],2)
        self.assertEqual(final["locks"]["w"],square("a3"))
        self.assertEqual(pos["board"],before["board"])

    def test_u13_crowning_and_flying_jump_lands_just_beyond_target(self):
        pos=position("w",[("c7","w","p"),("a5","b","h"),("d2","b","p")])
        after=plays(draughts,pos,("c7","b8"))
        self.assertEqual((piece(after,"b8")["type"],after["turn"]),("h","b"))
        self.assertTrue(after["resolution"]["crowned"])
        pos=position("w",[("a3","w","h"),("d6","b","p")])
        self.assertEqual(selected(draughts,pos,"a3","e7")["capture"],square("d6"))
        self.assertFalse(any(m["to"]==square("f8") for m in draughts.turn_options(pos)["moves"]))

    def test_u14_lock_prefers_unlocked_capture_and_uses_locked_when_only_choice(self):
        pos=position("w",[("a3","w","p"),("b4","b","p"),("e3","w","p"),("f4","b","p")])
        pos["locks"]["w"]=square("a3")
        self.assertEqual(origins(draughts.turn_options(pos)),{square("e3")})
        pos["board"][square("f4")]=None
        self.assertEqual(origins(draughts.turn_options(pos)),{square("a3")})

    def test_u15_queue_skips_revival_and_uses_friendly_jump(self):
        pos=position("b",[("a3","b","p"),("b2","b","p",{"card":"push"})])
        pos["queue"]["b"]=["revive","friendly"]
        options=draughts.turn_options(pos)
        self.assertEqual((options["skipped"],options["card"]),(["revive"],"friendly"))
        chosen=selected(draughts,pos,"a3","c1")
        self.assertTrue(chosen["friendly"])
        after=draughts.play(pos,chosen,options)
        self.assertEqual((after["resolution"]["cards"],after["queue"]["b"],after["reserve"]["b"]),([],[],1))

    def test_u16_revival_requires_dark_home_square(self):
        for side,target in [("w","b2"),("b","b8")]:
            with self.subTest(side=side):
                pos=position(side,[("c5",side,"p")])
                pos["queue"][side]=["revive"]
                pos["reserve"][side]=1
                after=plays(draughts,pos,(None,target))
                self.assertEqual((piece(after,target)["id"],after["reserve"][side]),(64,0))
                self.assertEqual(after["resolution"]["route"],[square(target)])

    def test_u17_push_excludes_king_and_skips_when_no_pawn_moves(self):
        pos=position("w",[("a3","w","h"),("e3","w","p")])
        pos["queue"]["w"]=["push"]
        self.assertEqual(origins(draughts.turn_options(pos)),{square("e3")})
        pos["board"][square("e3")]=None
        options=draughts.turn_options(pos)
        self.assertEqual(options["skipped"],["push"])
        self.assertFalse(options["forced"])
        self.assertTrue(any(abs(m["to"]-m["from"])>9 for m in options["moves"]))

    def test_u18_hybrid_checker_cannot_directly_capture_king(self):
        pos=position("b",[("b4","b","p"),("c3","w","k")],mixed=True)
        options=draughts.turn_options(pos)
        self.assertFalse(options["mustCapture"])
        self.assertFalse(any("capture" in m for m in options["moves"]))

    def test_u19_invalid_draughts_origin_does_not_mutate(self):
        pos=draughts.start()
        before=deepcopy(pos)
        with self.assertRaisesRegex(ValueError,"start on a piece"):
            draughts.play(pos,{"from":32,"to":33})
        self.assertEqual(pos,before)


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.pos=position("w",[("e1","w","k"),("b4","w","p",{"cards":["lock"]}),
                               ("a5","b","p",{"cards":["duel","push"]})],mixed=True)
        self.chosen=selected(hybrid,self.pos,"b4","a5")

    def test_u20_armies_and_duel_deck(self):
        start=hybrid.start()
        self.assertEqual(start["turn"],"w")
        self.assertEqual(sum(bool(p and p["side"]=="w") for p in start["board"]),16)
        self.assertEqual(sum(bool(p and p["side"]=="b") for p in start["board"]),12)
        self.assertIn("duel",game.deck_for("hybrid","b"))
        self.assertNotIn("duel",game.deck_for("hybrid","w"))

    def test_u21_duel_requires_resolution_before_capture(self):
        before=deepcopy(self.pos)
        self.assertTrue(hybrid.challenges(self.pos,self.chosen))
        with self.assertRaisesRegex(ValueError,"Resolve Tic Tac Toe"):
            hybrid.play(self.pos,self.chosen)
        self.assertEqual(self.pos,before)

    def test_u22_checker_win_reverses_capture_and_consumes_only_duel(self):
        before=deepcopy(self.pos)
        after=hybrid.play(self.pos,self.chosen,duel_winner="b")
        self.assertTrue(after["resolution"]["reversed"])
        self.assertIsNone(piece(after,"b4"))
        self.assertEqual(piece(after,"a5")["cards"],["push"])
        self.assertEqual((after["locks"]["b"],after["reserve"]["w"]),(square("a5"),1))
        self.assertEqual(self.pos,before)

    def test_u23_draw_and_chess_win_commit_capture(self):
        for winner in (None,"w"):
            with self.subTest(winner=winner):
                after=hybrid.play(self.pos,self.chosen,duel_winner=winner)
                self.assertFalse(after["resolution"]["reversed"])
                self.assertEqual(after["resolution"]["duelWinner"],winner)
                self.assertEqual((piece(after,"a5")["side"],after["queue"]["b"],after["reserve"]["b"]),("w",["push"],1))

    def test_u24_king_lost_in_duel_ends_match(self):
        pos=position("w",[("b4","w","k"),("a5","b","p",{"cards":["duel"]})],mixed=True)
        after=hybrid.play(pos,selected(hybrid,pos,"b4","a5"),duel_winner="b")
        opts=hybrid.turn_options(after)
        self.assertEqual((after["duelWin"],opts["moves"]),("b",[]))
        self.assertEqual(game.outcome_for("hybrid",after,opts)["reason"],"duel_king")

    def test_u25_checker_turn_uses_draughts_engine(self):
        pos=hybrid.start()
        pos["turn"]="b"
        opts=hybrid.turn_options(pos)
        self.assertEqual(opts,draughts.turn_options(pos))
        self.assertEqual(hybrid.play(pos,opts["moves"][0],opts)["resolution"]["kind"],"draughts")

    def test_u26_white_skips_unavailable_queue_entry_then_consumes_push(self):
        pos=hybrid.start()
        pos["queue"]["w"]=["revive","push"]
        opts=hybrid.turn_options(pos)
        self.assertEqual((opts["skipped"],opts["card"],opts["forced"]),(["revive"],"push",True))
        after=hybrid.play(pos,opts["moves"][0],opts)
        self.assertEqual(after["queue"]["w"],[])
        self.assertFalse(after["resolution"]["duel"])

    def test_u27_white_revival_and_friendly_capture(self):
        pos=position("w",[("e1","w","k"),("a1","w","r"),("a2","w","p")],mixed=True)
        pos["queue"]["w"]=["revive"]
        pos["reserve"]["w"]=1
        after=plays(hybrid,pos,(None,"b2"))
        self.assertEqual((after["nextId"],after["reserve"]["w"]),(65,0))
        pos["queue"]["w"]=["friendly"]
        after=plays(hybrid,pos,("a1","a2"))
        self.assertEqual(piece(after,"a2")["side"],"w")
        self.assertEqual(after["resolution"]["cards"],[])

    def test_u28_a_locked_king_still_can_escape_check_if_it_must(self):
        pos=position("w",[("a1","w","k"),("a8","b","q"),("c2","b","p")],mixed=True)
        pos["locks"]["w"]=square("a1")
        opts=hybrid.turn_options(pos)
        self.assertTrue(opts["checked"])
        self.assertEqual(origins(opts),{square("a1")})



def room(mode="chess"):
    return rooms.Room("QATEST01",mode,game.ENGINES[mode].start(),{
        "w":rooms.Seat("QA White",sha256(b"W"*43).digest()),
        "b":rooms.Seat("QA Black",sha256(b"B"*43).digest())})


class XOAndOutcomes(unittest.TestCase):
    def test_u29_winning_lines_and_ninth_cell_draw(self):
        for line in [(0,1,2),(0,3,6),(0,4,8),(2,4,6)]:
            with self.subTest(line=line):
                other=[c for c in range(9) if c not in line]
                result=duel.start()
                for cell in (line[0],other[0],line[1],other[1],line[2]):
                    result=duel.play(result,cell)
                self.assertEqual((result["winner"],result["line"]),("b",list(line)))
        result=duel.start()
        for cell in (0,1,3,4,7,5,2,6,8):
            result=duel.play(result,cell)
        self.assertTrue(result["done"])
        self.assertIsNone(result["winner"])

    def test_u30_invalid_duplicate_and_terminal_moves_preserve_object(self):
        original=duel.start()
        for cell in (-1,9,1.0,True,None,"0"):
            with self.subTest(cell=cell):
                self.assertIs(duel.play(original,cell),original)
        moved=duel.play(original,0)
        self.assertIsNone(original["cells"][0])
        self.assertIs(duel.play(moved,0),moved)
        for cell in (3,1,4,2):
            moved=duel.play(moved,cell)
        self.assertIs(duel.play(moved,5),moved)

    def test_u31_checkmate_stalemate_and_bare_kings(self):
        mate=plays(chess,chess.start(),("f2","f3"),("e7","e5"),("g2","g4"),("d8","h4"))
        self.assertEqual(game.outcome_for("chess",mate,chess.turn_options(mate)),
                         {"winner":"b","reason":"checkmate"})
        stalemate=position("b",[("a8","b","k"),("c6","w","k"),("b6","w","q")])
        self.assertEqual(game.outcome_for("chess",stalemate,chess.turn_options(stalemate)),
                         {"winner":None,"reason":"stalemate"})
        stalemate["board"][square("b6")]=None
        self.assertEqual(game.outcome_for("chess",stalemate,chess.turn_options(stalemate))["reason"],"kings_only")

    def test_u32_draughts_no_moves_vs_no_pieces_and_xo_check(self):
        blocked=position("b",[("a1","b","p")])
        self.assertEqual(game.outcome_for("draughts",blocked,draughts.turn_options(blocked))["reason"],"no_moves")
        empty=position("b",[])
        self.assertEqual(game.outcome_for("draughts",empty,draughts.turn_options(empty))["reason"],"no_pieces")
        mixed=hybrid.start()
        mixed["duelWin"]="b"
        self.assertEqual(game.outcome_for("hybrid",mixed,hybrid.turn_options(mixed))["reason"],"duel_check")


class ValidationAndRoomTests(unittest.TestCase):
    def test_u33_coordinates_bounds_require_integer(self):
        for good in (0,63):
            self.assertEqual(models.MoveChoice.model_validate({"to":good}).to,good)
        for bad in (-1,64,1.0,"4",True,None):
            with self.subTest(bad=bad),self.assertRaises(ValidationError):
                models.MoveChoice.model_validate({"to":bad})

    def test_u34_name_normalizes_and_rejects_invalid_length_controls(self):
        self.assertEqual(rooms.PlayerRequest(name="  Ａ  คนไทย 😀 ").name,"A คนไทย 😀")
        self.assertEqual(len(rooms.PlayerRequest(name="😀"*24).name),24)
        for invalid in ("","  ","a"*25,"A\u202eB",None):
            with self.subTest(invalid=invalid),self.assertRaises(ValidationError):
                rooms.PlayerRequest(name=invalid)

    def test_u35_token_input_is_cryptorandom_and_only_hash_stored(self):
        with patch.object(rooms,"token_urlsafe",return_value="A"*43) as generator:
            token,seat=rooms._new_seat("Player")
        generator.assert_called_once_with(32)
        self.assertEqual(seat.secret_hash,sha256(token.encode("ascii")).digest())
        self.assertNotIn(token,str(seat))

    def test_u36_snapshot_hides_opponent_skill_and_inactive_options(self):
        current=room("hybrid")
        rooms._place_skills(current,"w",{"lock":48,"revive":49,"friendly":50,"push":51})
        rooms._place_skills(current,"b",{"lock":8,"revive":1,"friendly":12,"push":17,"duel":17})
        white=rooms._snapshot(current,"w")
        black=rooms._snapshot(current,"b")
        self.assertTrue(white["options"]["moves"])
        self.assertIsNone(black["options"])
        for side,snap in [("w",white),("b",black)]:
            self.assertTrue(all(("skills" in p)==(p["side"]==side) for p in snap["board"] if p))
        white["board"][48]["skills"].append("push")
        self.assertEqual(current.state["board"][48]["cards"],["lock"])

    def test_u37_invalid_layout_does_not_commit(self):
        for layout in [{"lock":48},{"lock":48,"revive":48,"friendly":50,"push":51},
                       {"lock":60,"revive":49,"friendly":50,"push":51}]:
            current=room()
            before=deepcopy(current.state)
            with self.subTest(layout=layout),self.assertRaises(HTTPException) as err:
                rooms._place_skills(current,"w",layout)
            self.assertEqual(err.exception.status_code,422)
            self.assertEqual(current.state,before)
            self.assertFalse(current.placements)

    def test_u38_seat_is_side_specific_and_auth_failure_logged(self):
        current=room()
        for token,side in [("W"*43,"w"),("B"*43,"b")]:
            credential=HTTPAuthorizationCredentials(scheme="Bearer",credentials=token)
            self.assertEqual(rooms._seat_for(current,credential),side)
        with patch.object(rooms,"_audit") as auditor,self.assertRaises(HTTPException) as err:
            rooms._seat_for(current,None)
        self.assertEqual(err.exception.status_code,401)
        auditor.assert_called_once_with("room_authorization_denied",current,status=401)

    def test_u39_waiting_lifetime_and_active_lifetime_boundaries(self):
        waiting=room()
        waiting.seats.pop("b")
        active=room()
        waiting.changed_at=active.changed_at=10
        cache={"wait":waiting,"active":active}
        with patch.object(rooms,"_rooms",cache),patch.object(rooms,"_audit") as audit:
            rooms._remove_expired_rooms(10+rooms.WAITING_ROOM_LIFETIME-1)
            self.assertIn("wait",cache)
            rooms._remove_expired_rooms(10+rooms.WAITING_ROOM_LIFETIME)
            self.assertNotIn("wait",cache)
            self.assertIn("active",cache)
            rooms._remove_expired_rooms(10+rooms.ROOM_LIFETIME)
            self.assertNotIn("active",cache)
            self.assertEqual(audit.call_count,2)

    def test_u40_expired_creation_entries_pruned_and_other_source_not_limited(self):
        now=100.0
        events=deque([(now-rooms.CREATE_WINDOW,"A"),(now-1,"A")])
        with patch.object(rooms,"_creations",events),patch.object(rooms,"_rooms",{}), \
                patch.object(rooms,"CREATE_LIMIT",1),patch.object(rooms,"_audit"):
            with self.assertRaises(HTTPException) as err:
                rooms._enforce_creation_quota("A",now)
            self.assertEqual(err.exception.status_code,429)
            self.assertEqual(err.exception.headers["Retry-After"],str(rooms.CREATE_WINDOW-1))
            rooms._enforce_creation_quota("B",now)
            self.assertEqual(len(events),1)

