import os
import time
import json
import random
import asyncio
from collections import Counter

from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import F

from vrzdk import router, bot, run

# Database
DB_FILE = "capsun_db.json"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

def update_user_stats(user_id, name, score_delta, is_winner):
    db = load_db()
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"name": name, "games_played": 0, "total_score": 0, "wins": 0}
    db[uid]["name"] = name
    db[uid]["games_played"] += 1
    db[uid]["total_score"] += score_delta
    if is_winner:
        db[uid]["wins"] += 1
    save_db(db)

# Cards
SUITS = ['♠', '♥', '♣', '♦']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
RANK_VALUES = {r: i+2 for i, r in enumerate(RANKS)}

class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
        self.value = RANK_VALUES[rank]
        
    def __repr__(self):
        return f"{self.rank}{self.suit}"

def create_deck():
    deck = [Card(r, s) for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck

def evaluate_hand(cards):
    vals = sorted([c.value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    counts = Counter(vals)
    counts_sorted = sorted([(count, val) for val, count in counts.items()], reverse=True)
    
    is_flush = len(cards) == 5 and len(set(suits)) == 1
    
    is_straight = False
    if len(cards) == 5:
        if len(set(vals)) == 5 and vals[0] - vals[-1] == 4:
            is_straight = True
        elif vals == [14, 5, 4, 3, 2]:
            is_straight = True
            vals = [5, 4, 3, 2, 14] 
            
    if is_straight and is_flush:
        return (9, vals[0]) 
        
    if counts_sorted[0][0] == 4:
        return (8, counts_sorted[0][1], counts_sorted[1][1]) 
        
    if counts_sorted[0][0] == 3 and len(counts_sorted) > 1 and counts_sorted[1][0] >= 2:
        return (7, counts_sorted[0][1], counts_sorted[1][1]) 
        
    if is_flush:
        return (6, *vals) 
        
    if is_straight:
        if vals == [5, 4, 3, 2, 14]:
            return (5, 5) 
        return (5, vals[0]) 
        
    if counts_sorted[0][0] == 3:
        kickers = [v for c, v in counts_sorted[1:]]
        return (4, counts_sorted[0][1], *kickers) 
        
    if counts_sorted[0][0] == 2 and len(counts_sorted) > 1 and counts_sorted[1][0] == 2:
        kickers = [v for c, v in counts_sorted[2:]]
        return (3, counts_sorted[0][1], counts_sorted[1][1], *kickers) 
        
    if counts_sorted[0][0] == 2:
        kickers = [v for c, v in counts_sorted[1:]]
        return (2, counts_sorted[0][1], *kickers) 
        
    return (1, *vals)

def get_hand_name(eval_tuple):
    names = {
        1: "High Card", 2: "Pair", 3: "Two Pair", 4: "Three of a Kind",
        5: "Straight", 6: "Flush", 7: "Full House", 8: "Four of a Kind", 9: "Straight Flush"
    }
    return names[eval_tuple[0]]

def get_royalty(hand_tuple, position):
    rank = hand_tuple[0]
    if position == 'back':
        if rank == 9: return 5
        if rank == 8: return 4
    elif position == 'middle':
        if rank == 9: return 10
        if rank == 8: return 8
        if rank == 7: return 2
    elif position == 'front':
        if rank == 4: return 3
    return 0

# Game State
games = {} # chat_id -> game session dict
arrange_sessions = {} # user_id -> arrange state dict

def generate_arrange_text(session):
    cards = session["cards"]
    atas_cards = [cards[i] for i in session["atas"]]
    tengah_cards = [cards[i] for i in session["tengah"]]
    bawah_cards = [cards[i] for i in session["bawah"]]
    
    atas_str = " ".join([str(c) for c in atas_cards]) or "-"
    tengah_str = " ".join([str(c) for c in tengah_cards]) or "-"
    bawah_str = " ".join([str(c) for c in bawah_cards]) or "-"
    
    active_row_name = session["active_row"].capitalize()
    
    text = (f"🎴 <b>Susun Kartumu!</b>\n\n"
            f"🔼 <b>Atas (3):</b> {atas_str}\n"
            f"▶️ <b>Tengah (5):</b> {tengah_str}\n"
            f"🔽 <b>Bawah (5):</b> {bawah_str}\n\n"
            f"Sedang mengisi baris: <b>{active_row_name}</b>\n"
            f"<i>Pilih baris dengan tombol di bawah, lalu klik kartu untuk mengisi.</i>")
            
    if len(atas_cards) == 3 and len(tengah_cards) == 5 and len(bawah_cards) == 5:
        front_eval = evaluate_hand(atas_cards)
        middle_eval = evaluate_hand(tengah_cards)
        back_eval = evaluate_hand(bawah_cards)
        
        is_pao = back_eval < middle_eval or middle_eval < front_eval
        
        text += "\n\n<b>--- EVALUASI SEMENTARA ---</b>\n"
        text += f"Atas: {get_hand_name(front_eval)}\n"
        text += f"Tengah: {get_hand_name(middle_eval)}\n"
        text += f"Bawah: {get_hand_name(back_eval)}\n"
        
        if is_pao:
            text += "\n⚠️ <b>STATUS: PAO!</b> (Susunan Salah)\n"
            text += "<i>Pastikan kombinasi Bawah >= Tengah >= Atas. Jika dikunci, Anda otomatis kalah!</i>"
        else:
            text += "\n✅ <b>STATUS: AMAN</b> (Susunan Benar)\n"
            text += "<i>Silakan klik Kunci Susunan jika sudah yakin.</i>"
            
    return text

def build_arrange_keyboard(user_id):
    session = arrange_sessions.get(user_id)
    if not session:
        return None
        
    cards = session["cards"]
    atas = session["atas"]
    tengah = session["tengah"]
    bawah = session["bawah"]
    active_row = session["active_row"]
    
    placed = set(atas + tengah + bawah)
    
    kb = []
    
    # Row selection buttons
    row_btns = []
    for r in ["atas", "tengah", "bawah"]:
        text = f"{'✅ ' if active_row == r else ''}{r.capitalize()}"
        row_btns.append(InlineKeyboardButton(text=text, callback_data=f"arrange_row_{r}"))
    kb.append(row_btns)
    
    # Card buttons (only unplaced)
    unplaced_indices = [i for i in range(13) if i not in placed]
    
    row = []
    for i in unplaced_indices:
        text = str(cards[i])
        btn = InlineKeyboardButton(text=text, callback_data=f"arrange_card_{i}")
        row.append(btn)
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
        
    # Control buttons
    reset_row = [
        InlineKeyboardButton(text="🔄 Reset Semua", callback_data="arrange_reset"),
        InlineKeyboardButton(text=f"🔄 Reset {active_row.capitalize()}", callback_data="arrange_reset_row")
    ]
    kb.append(reset_row)
    
    if len(placed) == 13:
        kb.append([InlineKeyboardButton(text="✅ Kunci Susunan", callback_data="arrange_confirm")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(Command("capsun"))
async def cmd_capsun(msg: Message):
    chat_id = msg.chat.id
    if chat_id in games and games[chat_id]["state"] == "waiting":
        await msg.reply("Sudah ada game menunggu pemain. Join dengan tombol di bawah!")
        return
    if chat_id in games and games[chat_id]["state"] == "playing":
        await msg.reply("Game sedang berlangsung!")
        return

    games[chat_id] = {
        "players": {},
        "state": "waiting",
        "creator": msg.from_user.id
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Join", callback_data="capsun_join")],
        [InlineKeyboardButton(text="Start Game", callback_data="capsun_start")]
    ])
    
    await msg.answer("🃏 <b>Game Capsa Susun dibuka!</b>\nMinimal 2 pemain, maksimal 4 pemain.", reply_markup=kb)

@router.callback_query(F.data == "capsun_join")
async def cb_join(query: CallbackQuery):
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    name = query.from_user.first_name

    if chat_id not in games or games[chat_id]["state"] != "waiting":
        await query.answer("Tidak ada game yang bisa di-join.", show_alert=True)
        return

    game = games[chat_id]
    if user_id in game["players"]:
        await query.answer("Kamu sudah join!", show_alert=True)
        return
        
    if len(game["players"]) >= 4:
        await query.answer("Game penuh!", show_alert=True)
        return

    game["players"][user_id] = {
        "name": name,
        "cards": [],
        "arranged": None,
        "pao": False,
        "finished": False
    }
    
    players_text = "\n".join([f"- {p['name']}" for p in game["players"].values()])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Join", callback_data="capsun_join")],
        [InlineKeyboardButton(text="Start Game", callback_data="capsun_start")]
    ])
    
    await query.message.edit_text(
        f"🃏 <b>Game Capsa Susun dibuka!</b>\nPemain ({len(game['players'])}/4):\n{players_text}",
        reply_markup=kb
    )
    await query.answer("Berhasil join!")

@router.callback_query(F.data == "capsun_start")
async def cb_start(query: CallbackQuery):
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    if chat_id not in games or games[chat_id]["state"] != "waiting":
        await query.answer("Tidak ada game yang bisa dimulai.", show_alert=True)
        return

    game = games[chat_id]
    
    if len(game["players"]) < 2:
        await query.answer("Minimal 2 pemain!", show_alert=True)
        return

    if user_id != game["creator"]:
        await query.answer("Hanya pembuat game yang bisa start!", show_alert=True)
        return

    game["state"] = "playing"
    
    deck = create_deck()
    
    for uid, player in game["players"].items():
        player["cards"] = deck[:13]
        deck = deck[13:]
        
    bot_info = await bot.me()
    
    enc_chat_id = str(chat_id).replace("-", "M")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Susun Kartu (PM)", url=f"https://t.me/{bot_info.username}?start=capsun_{enc_chat_id}")]
    ])
    
    mentions = ", ".join([f"<a href='tg://user?id={uid}'>{p['name']}</a>" for uid, p in game["players"].items()])
    await query.message.answer(f"Kartu sudah dibagikan ke {mentions}.\nSilahkan klik tombol di bawah untuk menyusun di PM bot.", reply_markup=kb)

    await query.message.edit_text(query.message.text + "\n\n<b>Game Dimulai!</b> Waktu menyusun: 17 menit.")
    await query.answer("Game Dimulai!")
    asyncio.create_task(game_timer(chat_id))

async def game_timer(chat_id):
    await asyncio.sleep(1020)  # 17 minutes
    if chat_id in games and games[chat_id]["state"] == "playing":
        game = games[chat_id]
        all_finished = all(p.get("finished", False) for p in game["players"].values())
        if not all_finished:
            await bot.send_message(chat_id, "⏳ Waktu habis (17 menit)! Pemain yang belum /finish otomatis PAO/dikunci.")
            for uid, p in game["players"].items():
                if not p.get("finished", False):
                    if p["arranged"] is None:
                        dummy_cards = p["cards"]
                        p["arranged"] = {
                            "front": dummy_cards[0:3],
                            "middle": dummy_cards[3:8],
                            "back": dummy_cards[8:13],
                            "front_eval": evaluate_hand(dummy_cards[0:3]),
                            "middle_eval": evaluate_hand(dummy_cards[3:8]),
                            "back_eval": evaluate_hand(dummy_cards[8:13])
                        }
                        p["pao"] = True
                    p["finished"] = True
            await calculate_and_announce_results(chat_id)

@router.message(Command("start"))
async def cmd_start_pm(msg: Message):
    if msg.chat.type != "private":
        return
        
    args = msg.text.split()
    if len(args) > 1 and args[1].startswith("capsun_"):
        chat_id_str = args[1].replace("capsun_", "").replace("M", "-")
        try:
            chat_id = int(chat_id_str)
        except:
            return
            
        if chat_id not in games:
            await msg.answer("Game tidak ditemukan atau sudah selesai.")
            return
            
        game = games[chat_id]
        if msg.from_user.id not in game["players"]:
            await msg.answer("Kamu tidak terdaftar di game ini.")
            return
            
        player = game["players"][msg.from_user.id]
        if player.get("finished", False):
            await msg.answer("Kamu sudah mengunci (/finish) susunan kartumu. Menunggu pemain lain selesai.")
            return
            
        # Init session
        arrange_sessions[msg.from_user.id] = {
            "chat_id": chat_id,
            "cards": player["cards"],
            "atas": [],
            "tengah": [],
            "bawah": [],
            "active_row": "bawah"
        }
        
        text = generate_arrange_text(arrange_sessions[msg.from_user.id])
        await msg.answer(text, reply_markup=build_arrange_keyboard(msg.from_user.id))

@router.message(Command("finish"))
async def cmd_finish(msg: Message):
    if msg.chat.type != "private":
        return
        
    user_id = msg.from_user.id
    active_chat_id = None
    for cid, game in games.items():
        if game["state"] == "playing" and user_id in game["players"]:
            active_chat_id = cid
            break
            
    if not active_chat_id:
        return
        
    game = games[active_chat_id]
    player = game["players"][user_id]
    
    if player["arranged"] is None:
        await msg.reply("Susun kartumu terlebih dahulu sebelum mengetik /finish!")
        return
        
    if player.get("finished", False):
        return
        
    player["finished"] = True
    await msg.reply("✅ Susunan berhasil dikunci! Menunggu pemain lain...")
    
    await bot.send_message(active_chat_id, f"✅ <b>{player['name']}</b> telah menyusun kartunya.")
    
    all_finished = all(p.get("finished", False) for p in game["players"].values())
    if all_finished:
        await calculate_and_announce_results(active_chat_id)

@router.callback_query(F.data.startswith("arrange_"))
async def cb_arrange(query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    
    if user_id not in arrange_sessions:
        await query.answer("Sesi susun kartu tidak ditemukan atau sudah kadaluarsa.", show_alert=True)
        return
        
    session = arrange_sessions[user_id]
    chat_id = session["chat_id"]
    
    if chat_id not in games or games[chat_id]["state"] != "playing":
        await query.answer("Game sudah selesai.", show_alert=True)
        return
        
    game = games[chat_id]
    player = game["players"][user_id]
    
    if player.get("finished", False):
        await query.answer("Susunan sudah dikunci!", show_alert=True)
        return
        
    if data == "arrange_reset":
        session["atas"] = []
        session["tengah"] = []
        session["bawah"] = []
        session["active_row"] = "bawah"
        
        await query.message.edit_text(generate_arrange_text(session), reply_markup=build_arrange_keyboard(user_id))
        await query.answer("Semua baris direset!")
        return
        
    if data == "arrange_reset_row":
        active = session["active_row"]
        session[active] = []
        
        await query.message.edit_text(generate_arrange_text(session), reply_markup=build_arrange_keyboard(user_id))
        await query.answer(f"Baris {active.capitalize()} direset!")
        return
        
    if data == "arrange_confirm":
        if len(session["atas"]) + len(session["tengah"]) + len(session["bawah"]) != 13:
            await query.answer("Susun semua kartu dulu!", show_alert=True)
            return
            
        # evaluate and lock
        cards = session["cards"]
        front_cards = [cards[i] for i in session["atas"]]
        middle_cards = [cards[i] for i in session["tengah"]]
        back_cards = [cards[i] for i in session["bawah"]]
        
        front_eval = evaluate_hand(front_cards)
        middle_eval = evaluate_hand(middle_cards)
        back_eval = evaluate_hand(back_cards)
        
        pao = False
        if back_eval < middle_eval or middle_eval < front_eval:
            pao = True
            
        player["arranged"] = {
            "front": front_cards,
            "middle": middle_cards,
            "back": back_cards,
            "front_eval": front_eval,
            "middle_eval": middle_eval,
            "back_eval": back_eval
        }
        player["pao"] = pao
        player["finished"] = True
        
        front_str = " ".join([str(c) for c in front_cards])
        middle_str = " ".join([str(c) for c in middle_cards])
        back_str = " ".join([str(c) for c in back_cards])
        
        reply_text = f"✅ <b>Susunan Kartu Terkunci:</b>\n\nAtas: {front_str} ({get_hand_name(front_eval)})\nTengah: {middle_str} ({get_hand_name(middle_eval)})\nBawah: {back_str} ({get_hand_name(back_eval)})"
        
        if pao:
            reply_text += "\n\n⚠️ <b>PERINGATAN: Susunan ini PAO (Bawah &lt; Tengah atau Tengah &lt; Atas). Kamu otomatis kalah.</b>"
            
        await query.message.edit_text(reply_text)
        await query.answer("Susunan dikunci!")
        
        del arrange_sessions[user_id]
        
        await bot.send_message(chat_id, f"✅ <b>{player['name']}</b> telah menyusun kartunya.")
        
        # Check if all finished
        all_finished = all(p.get("finished", False) for p in game["players"].values())
        if all_finished:
            await calculate_and_announce_results(chat_id)
            
        return

    if data.startswith("arrange_row_"):
        row = data.split("_")[2]
        session["active_row"] = row
        await query.message.edit_text(generate_arrange_text(session), reply_markup=build_arrange_keyboard(user_id))
        await query.answer(f"Mengisi baris {row.capitalize()}")
        return
        
    if data.startswith("arrange_card_"):
        try:
            idx = int(data.split("_")[2])
        except:
            return
            
        active = session["active_row"]
        limit = 3 if active == "atas" else 5
        
        if len(session[active]) >= limit:
            await query.answer(f"Baris {active.capitalize()} sudah penuh!", show_alert=True)
            return
            
        session[active].append(idx)
        
        # Auto-switch to next empty row if current is full
        if len(session[active]) == limit:
            if active == "bawah" and len(session["tengah"]) < 5:
                session["active_row"] = "tengah"
            elif active == "tengah" and len(session["atas"]) < 3:
                session["active_row"] = "atas"
            elif active == "atas" and len(session["tengah"]) < 5:
                session["active_row"] = "tengah"
            elif active == "bawah" and len(session["atas"]) < 3:
                session["active_row"] = "atas"
                
        await query.message.edit_text(generate_arrange_text(session), reply_markup=build_arrange_keyboard(user_id))
        await query.answer()
        return

async def calculate_and_announce_results(chat_id):
    game = games[chat_id]
    players = game["players"]
    player_ids = list(players.keys())
    
    scores = {uid: 0 for uid in player_ids}
    score_breakdown = {uid: {"atas": 0, "tengah": 0, "bawah": 0, "tembus": 0, "royalty": 0, "pao": 0} for uid in player_ids}
    
    for i in range(len(player_ids)):
        for j in range(i+1, len(player_ids)):
            p1_id = player_ids[i]
            p2_id = player_ids[j]
            p1 = players[p1_id]
            p2 = players[p2_id]
            
            # Pao logic
            if p1["pao"] and not p2["pao"]:
                scores[p2_id] += 3; scores[p1_id] -= 3
                score_breakdown[p2_id]["pao"] += 3; score_breakdown[p1_id]["pao"] -= 3
                continue
            elif p2["pao"] and not p1["pao"]:
                scores[p1_id] += 3; scores[p2_id] -= 3
                score_breakdown[p1_id]["pao"] += 3; score_breakdown[p2_id]["pao"] -= 3
                continue
            elif p1["pao"] and p2["pao"]:
                continue # Draw if both pao
                
            # Normal Compare
            p1_wins = 0
            p2_wins = 0
            
            # Front
            if p1["arranged"]["front_eval"] > p2["arranged"]["front_eval"]: 
                p1_wins += 1; scores[p1_id] += 1; scores[p2_id] -= 1
                score_breakdown[p1_id]["atas"] += 1; score_breakdown[p2_id]["atas"] -= 1
            elif p1["arranged"]["front_eval"] < p2["arranged"]["front_eval"]: 
                p2_wins += 1; scores[p2_id] += 1; scores[p1_id] -= 1
                score_breakdown[p2_id]["atas"] += 1; score_breakdown[p1_id]["atas"] -= 1
            
            # Middle
            if p1["arranged"]["middle_eval"] > p2["arranged"]["middle_eval"]: 
                p1_wins += 1; scores[p1_id] += 1; scores[p2_id] -= 1
                score_breakdown[p1_id]["tengah"] += 1; score_breakdown[p2_id]["tengah"] -= 1
            elif p1["arranged"]["middle_eval"] < p2["arranged"]["middle_eval"]: 
                p2_wins += 1; scores[p2_id] += 1; scores[p1_id] -= 1
                score_breakdown[p2_id]["tengah"] += 1; score_breakdown[p1_id]["tengah"] -= 1
            
            # Back
            if p1["arranged"]["back_eval"] > p2["arranged"]["back_eval"]: 
                p1_wins += 1; scores[p1_id] += 1; scores[p2_id] -= 1
                score_breakdown[p1_id]["bawah"] += 1; score_breakdown[p2_id]["bawah"] -= 1
            elif p1["arranged"]["back_eval"] < p2["arranged"]["back_eval"]: 
                p2_wins += 1; scores[p2_id] += 1; scores[p1_id] -= 1
                score_breakdown[p2_id]["bawah"] += 1; score_breakdown[p1_id]["bawah"] -= 1
            
            # Tembus check
            if p1_wins == 3 and p2_wins == 0:
                scores[p1_id] += 3 
                scores[p2_id] -= 3
                score_breakdown[p1_id]["tembus"] += 3
                score_breakdown[p2_id]["tembus"] -= 3
            elif p2_wins == 3 and p1_wins == 0:
                scores[p2_id] += 3
                scores[p1_id] -= 3
                score_breakdown[p2_id]["tembus"] += 3
                score_breakdown[p1_id]["tembus"] -= 3
                
    # Royalties
    for uid, p in players.items():
        if p["pao"]: continue
        arr = p["arranged"]
        royalty = 0
        royalty += get_royalty(arr["back_eval"], 'back')
        royalty += get_royalty(arr["middle_eval"], 'middle')
        royalty += get_royalty(arr["front_eval"], 'front')
        
        # Royalty given by all other non-pao players
        for other_uid in player_ids:
            if other_uid != uid and not players[other_uid]["pao"]:
                scores[uid] += royalty
                scores[other_uid] -= royalty
                score_breakdown[uid]["royalty"] += royalty
                score_breakdown[other_uid]["royalty"] -= royalty
                
    # Formatting Results
    result_text = "🃏 <b>Hasil Capsa Susun</b> 🃏\n\n"
    
    # Save to db and find winner
    sorted_players = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    winner_score = sorted_players[0][1]
    
    for uid, score in sorted_players:
        p = players[uid]
        is_winner = (score == winner_score and score > 0)
        update_user_stats(uid, p["name"], score, is_winner)
        
        bd = score_breakdown[uid]
        pao_text = " [PAO!]" if p["pao"] else ""
        
        header_extras = []
        if bd['tembus'] != 0:
            header_extras.append(f"Tembus: {bd['tembus']:+}")
        if bd['royalty'] != 0:
            header_extras.append(f"Bonus: {bd['royalty']:+}")
            
        extra_str = f" <i>[{' | '.join(header_extras)}]</i>" if header_extras else ""
        if p["pao"]:
            extra_str = f" <i>[PAO: {bd['pao']:+}]</i>"
            
        result_text += f"👤 <b>{p['name']}</b>{pao_text}: {score} poin{extra_str}\n"
        
        arr = p["arranged"]
        front_str = " ".join([str(c) for c in arr["front"]])
        middle_str = " ".join([str(c) for c in arr["middle"]])
        back_str = " ".join([str(c) for c in arr["back"]])
        
        if not p["pao"]:
            result_text += f"  A: {front_str} ({get_hand_name(arr['front_eval'])}) [<b>{bd['atas']:+}</b>]\n"
            result_text += f"  T: {middle_str} ({get_hand_name(arr['middle_eval'])}) [<b>{bd['tengah']:+}</b>]\n"
            result_text += f"  B: {back_str} ({get_hand_name(arr['back_eval'])}) [<b>{bd['bawah']:+}</b>]\n"
        else:
            result_text += f"  A: {front_str} ({get_hand_name(arr['front_eval'])})\n"
            result_text += f"  T: {middle_str} ({get_hand_name(arr['middle_eval'])})\n"
            result_text += f"  B: {back_str} ({get_hand_name(arr['back_eval'])})\n"
        result_text += "\n"
        
    await bot.send_message(chat_id, result_text)
    
    # Cleanup game
    del games[chat_id]

@router.message(Command("leaderboard"))
async def cmd_leaderboard(msg: Message):
    db = load_db()
    if not db:
        await msg.reply("Belum ada data leaderboard.")
        return
        
    players = []
    for uid, data in db.items():
        skill_score = data["total_score"] + (data["wins"] * 10) 
        players.append({
            "name": data["name"],
            "total_score": data["total_score"],
            "games": data["games_played"],
            "wins": data["wins"],
            "skill": skill_score
        })
        
    players.sort(key=lambda x: x["skill"], reverse=True)
    
    top10 = players[:10]
    text = "🏆 <b>Leaderboard Capsa Susun</b> 🏆\n(Peringkat berdasar Total Poin & Wins)\n\n"
    for i, p in enumerate(top10):
        text += f"{i+1}. <b>{p['name']}</b>\n   Rating: {p['skill']} (Poin: {p['total_score']}, Menang: {p['wins']}, Main: {p['games']})\n"
        
    await msg.reply(text)

@router.message(Command("tutorial"))
async def cmd_tutorial(msg: Message):
    text = (
        "📚 <b>Tutorial Singkat Capsa Susun</b> 📚\n\n"
        "<b>1. Urutan Kartu & Kombinasi (Rendah - Tinggi)</b>\n"
        "Angka: 2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K, A\n"
        "Kombinasi Poker:\n"
        "🔸 <b>High Card:</b> Kartu acak tertinggi\n"
        "🔸 <b>Pair:</b> 2 kartu angka sama\n"
        "🔸 <b>Two Pair:</b> 2 pasang Pair\n"
        "🔸 <b>Three of a Kind:</b> 3 kartu angka sama\n"
        "🔸 <b>Straight:</b> 5 kartu urut angkanya\n"
        "🔸 <b>Flush:</b> 5 kartu sama lambang/warna\n"
        "🔸 <b>Full House:</b> Three of a Kind + Pair\n"
        "🔸 <b>Four of a Kind:</b> 4 kartu angka sama\n"
        "🔸 <b>Straight Flush:</b> 5 kartu urut & lambang sama\n\n"
        "<b>2. Cara Menyusun</b>\n"
        "Tiap pemain diberi 13 kartu. Susun menjadi 3 baris:\n"
        "👉 <b>Atas:</b> 3 kartu (Paling lemah)\n"
        "👉 <b>Tengah:</b> 5 kartu\n"
        "👉 <b>Bawah:</b> 5 kartu (Paling kuat)\n"
        "⚠️ <b>Syarat Wajib (PAO):</b> Kekuatan baris Bawah harus &gt;= Tengah, dan Tengah harus &gt;= Atas. Jika melanggar, Anda dinyatakan <b>PAO</b> dan otomatis kalah dari semua pemain!\n\n"
        "<b>3. Poin & Skor</b>\n"
        "🔹 Tiap baris yang menang diadu lawan pemain lain bernilai +1 poin, kalah -1.\n"
        "🔹 <b>Tembus:</b> Menang di semua baris (Atas, Tengah, Bawah) dari 1 pemain lawan, poin kemenangannya menjadi ganda (+6 poin dari lawan tersebut).\n"
        "🔹 <b>Bonus (Royalty):</b> Poin tambahan jika punya kombinasi spesial di posisi yang tepat (Bawah: Straight Flush/Four of a Kind, Tengah: Full House ke atas, Atas: Three of a Kind)."
    )
    await msg.reply(text)

if __name__ == "__main__":
    run()
