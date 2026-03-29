from __future__ import annotations

from typing import Any


def _add(tags: dict[str, dict[str, Any]], tag: str, confidence: float, evidence: str) -> None:
    existing = tags.get(tag)
    if existing is None or confidence > existing["confidence"]:
        tags[tag] = {"tag": tag, "confidence": round(float(confidence), 3), "evidence": evidence}


def _piece_value(chess: Any, piece_type: int) -> int:
    return {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
        chess.KING: 100,
    }.get(piece_type, 0)


def detect_tactical_tags(
    board_before: Any,
    board_after_played: Any,
    board_after_best: Any,
    played_pv: list[str],
    best_pv: list[str],
    move: Any,
    mover_color: Any,
    chess: Any,
) -> list[dict[str, Any]]:
    """Deterministic motif detector using board geometry + PV evidence.

    Returns list of dicts: {tag, confidence, evidence}
    """
    tags: dict[str, dict[str, Any]] = {}
    to_sq = move.to_square
    moved_piece = board_after_played.piece_at(to_sq)

    # Core forcing motifs from board geometry.
    if board_after_played.is_check():
        _add(tags, "mate threat", 0.62, "move gives check and creates immediate king pressure")

    if moved_piece is not None and moved_piece.color == mover_color:
        attacked = []
        for sq in board_after_played.attacks(to_sq):
            piece = board_after_played.piece_at(sq)
            if piece is not None and piece.color != mover_color:
                attacked.append((sq, piece))
        valuable_targets = [x for x in attacked if _piece_value(chess, x[1].piece_type) >= 3]
        if len(valuable_targets) >= 2:
            _add(tags, "double attack", 0.9, "moved piece attacks two valuable enemy targets")
            if moved_piece.piece_type in {chess.KNIGHT, chess.QUEEN, chess.BISHOP}:
                _add(tags, "fork", 0.86, "single piece attacks multiple enemy pieces")

    # Pin detection: any enemy piece pinned to king after move.
    enemy = not mover_color
    for sq, piece in board_after_played.piece_map().items():
        if piece.color == enemy and board_after_played.is_pinned(enemy, sq):
            _add(tags, "pin", 0.74, "enemy piece is pinned after move")
            break

    # Skewer heuristic: checking long-range attack through high-value then lower-value target.
    if moved_piece is not None and moved_piece.piece_type in {chess.BISHOP, chess.ROOK, chess.QUEEN}:
        for ray_sq in board_after_played.attacks(to_sq):
            front = board_after_played.piece_at(ray_sq)
            if front is None or front.color == mover_color:
                continue
            if _piece_value(chess, front.piece_type) < 5:
                continue
            _add(tags, "skewer", 0.58, "long-range piece attacks high-value target with latent follow-up")
            break

    # Discovered motifs.
    from_sq = move.from_square
    before_piece = board_before.piece_at(from_sq)
    if before_piece is not None:
        # If vacated square uncovers line attack from own rook/bishop/queen.
        for sq, p in board_after_played.piece_map().items():
            if p.color == mover_color and p.piece_type in {chess.ROOK, chess.BISHOP, chess.QUEEN}:
                if from_sq in board_after_played.attacks(sq):
                    _add(tags, "discovered attack", 0.64, "vacating move uncovers line-piece attack")
                    if board_after_played.is_check():
                        _add(tags, "discovered check", 0.88, "vacating move produces discovered check")
                    break

    # Exchange sacrifice.
    if board_before.is_capture(move):
        captured = board_before.piece_at(to_sq)
        if moved_piece is not None and captured is not None:
            if _piece_value(chess, moved_piece.piece_type) - _piece_value(chess, captured.piece_type) >= 2:
                _add(tags, "exchange sacrifice", 0.78, "higher-value piece traded down for dynamic compensation")

    # Promotion tactic.
    if move.promotion is not None:
        _add(tags, "promotion tactic", 0.95, "move is a pawn promotion")

    # Hanging piece: enemy piece attacked and undefended.
    for sq, piece in board_after_played.piece_map().items():
        if piece.color == enemy:
            attackers = board_after_played.attackers(mover_color, sq)
            defenders = board_after_played.attackers(enemy, sq)
            if attackers and not defenders:
                _add(tags, "hanging piece", 0.66, "move leaves enemy piece attacked with no defenders")
                break

    # Trapped piece: enemy mobility collapses.
    for sq, piece in board_before.piece_map().items():
        if piece.color != enemy:
            continue
        before_mob = len(list(board_before.generate_legal_moves(from_mask=chess.BB_SQUARES[sq])))
        after_mob = len(list(board_after_played.generate_legal_moves(from_mask=chess.BB_SQUARES[sq])))
        if before_mob >= 3 and after_mob <= 1:
            _add(tags, "trapped piece", 0.61, "enemy piece mobility sharply reduced")
            break

    # Back-rank tactic.
    if board_after_played.is_check() and board_after_played.king(enemy) is not None:
        ksq = board_after_played.king(enemy)
        rank = chess.square_rank(ksq)
        if rank in {0, 7}:
            _add(tags, "back-rank tactic", 0.72, "check/checkmate against back-rank king")

    # PV-evidence motifs (deterministic keyword/rule based).
    played_text = " ".join(played_pv).lower()
    best_text = " ".join(best_pv).lower()

    if played_text.count("+") >= 3:
        _add(tags, "perpetual-check resource", 0.7, "played PV contains repeated checking sequence")

    if best_text.startswith("mate") or "#" in best_text and "#" not in played_text:
        _add(tags, "miss", 0.85, "best PV indicates forcing mate that played line misses")

    keyword_map = {
        "fork": ["fork"],
        "pin": ["pin"],
        "skewer": ["skewer"],
        "discovered attack": ["discovered attack"],
        "discovered check": ["discovered check"],
        "double attack": ["double attack"],
        "removal of defender": ["removal", "defender"],
        "deflection": ["deflect", "deflection"],
        "decoy": ["decoy", "lure"],
        "interference": ["interference", "interpose"],
        "overload": ["overload", "overworked"],
        "clearance": ["clearance", "vacate"],
        "back-rank tactic": ["back-rank", "back rank"],
        "trapped piece": ["trapped piece", "trap"],
        "zwischenzug": ["zwischenzug", "intermezzo"],
        "promotion tactic": ["promotion", "="],
        "perpetual-check resource": ["perpetual", "perpetual-check"],
        "exchange sacrifice": ["exchange sacrifice", "sac"],
        "desperado": ["desperado"],
        "mate threat": ["mate threat", "threat mate"],
        "hanging piece": ["hanging piece", "undefended"],
    }
    for tag, kws in keyword_map.items():
        if any(kw in played_text for kw in kws) or any(kw in best_text for kw in kws):
            _add(tags, tag, 0.55, "PV evidence keyword match")

    # Mate threat via legal move generation: side to move can mate in one.
    for reply in board_after_played.legal_moves:
        probe = board_after_played.copy()
        probe.push(reply)
        if probe.is_checkmate():
            _add(tags, "mate threat", 0.9, "position contains mate-in-one threat")
            break

    return sorted(tags.values(), key=lambda t: (-t["confidence"], t["tag"]))
