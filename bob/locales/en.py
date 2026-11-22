"""English messages, keyed by the French source text (see bob/i18n.py)."""
MESSAGES: dict[str, str] = {
    'Je sèche sur celle-là 🥲 Tu peux me la redire autrement ?':
        "I'm stuck on that one 🥲 Can you put it another way?",
    "⚠️ J'ai pas pu aller au bout 🥲 Tu me relances ?":
        "⚠️ I couldn't finish that 🥲 Mind asking again?",
    'frais':
        'fresh',
    'neutre':
        'neutral',
    'optimal':
        'optimal',
    'productif':
        'productive',
    'fatigué':
        'tired',
    'surcharge':
        'overreaching',
    'surentraînement':
        'overtraining',
    'désentraînement':
        'detraining',
    'sous-entraînement':
        'undertraining',
    'transition':
        'transition',
    'bas':
        'low',
    'risque faible':
        'low risk',
    'modéré':
        'moderate',
    'risque modéré':
        'moderate risk',
    'élevé':
        'high',
    'risque élevé':
        'high risk',
    'risque très élevé':
        'very high risk',
    'Pour ta séance de {when} ({title}) :':
        'For your {when} session ({title}):',
    '👋 Configuration : ajoute TELEGRAM_CHAT_ID={chat_id} dans ton .env puis redémarre le conteneur.':
        '👋 Setup: add TELEGRAM_CHAT_ID={chat_id} to your .env, then restart the container.',
    "Oups, mon message n'est pas parti 🥲 Réessaie ?":
        "Oops, my message didn't go through 🥲 Try again?",
    '🎙️ Les messages vocaux sont désactivés (WHISPER_MODEL=off). Écris-moi plutôt.':
        '🎙️ Voice messages are turned off (WHISPER_MODEL=off). Text me instead.',
    '🎙️ Vocal trop long (max {minutes} min). Fais plus court ou écris-moi.':
        '🎙️ Voice message too long (max {minutes} min). Make it shorter or text me.',
    "❌ Je n'ai pas pu transcrire ce vocal ({error}). Réessaie ou écris-moi.":
        "❌ I couldn't transcribe that voice message ({error}). Try again or text me.",
    "🎙️ Je n'ai rien entendu de clair. Tu peux réessayer ?":
        "🎙️ I couldn't hear anything clear. Can you try again?",
    '🎙️ « {text} »':
        '🎙️ “{text}”',
    'Oups, une erreur de mon côté 🥲 Réessaie dans un instant ?':
        'Oops, something went wrong on my side 🥲 Try again in a moment?',
    "❌ Erreur technique : {error}. Rien n'est garanti côté agenda, vérifie-le.":
        '❌ Technical error: {error}. Nothing is guaranteed on the calendar side, check it.',
    '❌ Erreur technique':
        '❌ Technical error',
    'Déjà traité.':
        'Already handled.',
    "T'as mal où, et depuis quand ? Ça gêne à la marche ?":
        'Where does it hurt, and since when? Does it bother you when walking?',
    '✅ Oui, vas-y':
        '✅ Yes, go',
    '✏️ Modifier':
        '✏️ Change',
    '❌ Non':
        '❌ No',
    "C'est parti 👌":
        'On it 👌',
    'Ok, dis-moi ce que tu veux changer 👂':
        'OK, tell me what you want to change 👂',
    'Ok, on garde comme ça 👍':
        'OK, we keep it as is 👍',
    'tout est dans le panier 🎉':
        "everything's in the basket 🎉",
    '🛒 *Liste de courses* — {status}':
        '🛒 *Shopping list* — {status}',
    '_Touche un article quand il est dans le panier. Recettes : /recipes_':
        "_Tap an item once it's in the basket. Recipes: /recipes_",
    '🧹 Tout décocher':
        '🧹 Untick all',
    'Fraîches':
        'Fresh',
    'Normales':
        'Normal',
    'Lourdes':
        'Heavy',
    'Douleur':
        'Pain',
    '🛒 Pas de liste de courses en cours. Lance /shopping pour en créer une.':
        '🛒 No shopping list right now. Use /shopping to make one.',
    "🍳 Pas de liste de courses en cours : lance d'abord /shopping.":
        '🍳 No shopping list right now: run /shopping first.',
    '❌ Recettes impossibles : {error}':
        "❌ Couldn't get recipes: {error}",
    'Merci 🙏':
        'Thanks 🙏',
    'Cette liste a été remplacée : /list affiche la liste en cours.':
        'This list was replaced: /list shows the current one.',
    "🛒 La liste de courses ne répond pas pour l'instant. Réessaie dans un moment.":
        "🛒 The shopping list isn't answering right now. Try again in a moment.",
    "La cuisine ne répond pas, rien n'a changé. Réessaie dans un moment.":
        "The kitchen isn't answering, nothing changed. Try again in a moment.",
    "🛒 La liste est enregistrée, mais je n'arrive pas à l'afficher pour l'instant : /list la montrera dans un moment.":
        "🛒 The list is saved, but I can't show it right now: /list will show it in a moment.",
    '❌ Dreeve indisponible : {error}':
        '❌ Dreeve unavailable: {error}',
    'Aucun run trouvé dans Dreeve.':
        'No run found in Dreeve.',
    '{rpe}/10, ok 👌 Et les jambes ?':
        '{rpe}/10, got it 👌 And your legs?',
    'Aïe 😬':
        'Ouch 😬',
    "Alors, t'as senti comment ? De 0 (mort) à 10 (facile comme marcher) :":
        'So, how did it feel? From 0 (dead) to 10 (easy as walking):',
    "J'ai vu passer ta sortie 🏃 mais j'ai pas réussi à la regarder en détail 🥲 Tape /debrief pour réessayer.":
        "I saw your run come in 🏃 but couldn't look at it in detail 🥲 Type /debrief to try again.",
    '❌ Bilan impossible : {error}':
        "❌ Couldn't build the review: {error}",
    '📊 *Bilan de la semaine*':
        '📊 *Weekly review*',
    '❌ Indisponible : {error}':
        '❌ Unavailable: {error}',
    '*🧠 Ce que je sais de toi*':
        '*🧠 What I know about you*',
    '_Pour corriger : « oublie le #3 » ou dis-moi simplement ce qui a changé._':
        '_To correct it: “forget #3”, or just tell me what changed._',
    'Pour les mèmes, il me faut une clé GIPHY (GIPHY_API_KEY dans la config) 😅':
        'For memes I need a GIPHY key (GIPHY_API_KEY in the config) 😅',
    "J'ai pas trouvé de mème à la hauteur de ta journée 🥲 Réessaie ?":
        "Couldn't find a meme worthy of your day 🥲 Try again?",
    'Il me faut tes lieux (WEATHER_LOCATIONS, ex. maison et travail) pour trouver des boucles 😅':
        'I need your places (WEATHER_LOCATIONS, e.g. home and work) to find loops 😅',
    'Tu veux courir sur quoi ? 👟':
        'What do you want to run on? 👟',
    'Combien de km ? 📏':
        'How many km? 📏',
    'Demande expirée, relance /newroute':
        'Request expired, run /newroute again',
    '🛣️ Route':
        '🛣️ Road',
    '🌲 Nature':
        '🌲 Trail',
    '🔀 Mixte':
        '🔀 Mixed',
    'Je trouve pas « {place} » sur la carte 🤔 Essaie avec la ville, genre « bois de vincennes paris »':
        "Can't find “{place}” on the map 🤔 Try adding the city, like “central park new york”",
    "J'ai pas réussi à tracer de boucle là, réessaie dans un moment 🥲":
        "Couldn't draw a loop there, try again in a moment 🥲",
    ' sur route':
        ' road',
    ' nature':
        ' trail',
    'Pas trouvé de boucle{kind} 100 % inédite vers {place}, voilà la plus nouvelle 👇':
        "No 100% new{kind} loop near {place}, here's the newest one 👇",
    'Une boucle{kind} jamais faite depuis {place} 👀':
        "A{kind} loop you've never run from {place} 👀",
    '{count} boucles{kind} de ~{km} km depuis {place} 👇':
        '{count}{kind} loops of ~{km} km from {place} 👇',
    'boucle-{n}-{km}km.gpx':
        'loop-{n}-{km}km.gpx',
    "Les boucles sont prêtes mais Telegram n'a pas voulu les prendre 🥲 Réessaie ?":
        "The loops are ready but Telegram wouldn't take them 🥲 Try again?",
    "Dreeve n'est pas configuré.":
        "Dreeve isn't configured.",
    'Séances prévues (7 jours, ou /plan 14)':
        'Planned sessions (7 days, or /plan 14)',
    "Charge d'entraînement et volume récent":
        'Training load and recent volume',
    'Tes derniers runs':
        'Your latest runs',
    "Prévisions par lieu d'entraînement":
        'Forecast per training place',
    'Tes objectifs et le compte à rebours':
        'Your goals and the countdown',
    'Ce que le coach sait de toi':
        'What the coach knows about you',
    'Débrief IA de ton dernier run':
        'AI debrief of your last run',
    'Bilan IA de la semaine (prévu vs fait)':
        'AI weekly review (planned vs done)',
    'Liste de courses selon tes objectifs (7 j, ou /shopping 3)':
        'Shopping list for your goals (7 d, or /shopping 3)',
    'Ta liste de courses en cours, à cocher':
        'Your current shopping list, to tick off',
    'Recettes en boîtes pour ta liste de courses':
        'Meal-prep recipes for your shopping list',
    '2-3 boucles de course autour de chez toi ou du boulot (carte + GPX)':
        '2-3 running loops around home or work (map + GPX)',
    'Une boucle jamais courue : distance, route/nature/mixte, lieu (carte + GPX)':
        "A loop you've never run: distance, road/trail/mixed, place (map + GPX)",
    "Un mème qui résume ta journée d'entraînement":
        'A meme that sums up your training day',
    'Briefing IA complet et ajustement du programme':
        'Full AI briefing and plan adjustment',
    'Liste des commandes':
        'List of commands',
    "🎯 *Objectifs*\nAucun objectif enregistré. Dis-moi simplement ta prochaine course (date, distance, chrono visé) ou un objectif santé, je l'enregistre et je construis le plan à rebours.":
        "🎯 *Goals*\nNo goal saved yet. Just tell me your next race (date, distance, target time) or a health goal, I'll save it and build the plan backward from it.",
    '🎯 *Objectifs*':
        '🎯 *Goals*',
    "_Pour modifier : « décale mon semi au 14 mars », « vise plutôt 1h50 », « j'abandonne le trail »._":
        "_To change one: “move my half to March 14”, “aim for 1:50 instead”, “I'm dropping the trail race”._",
    '📅 *Programme, {days} prochains jours*':
        '📅 *Plan, next {days} days*',
    '📅 *Programme, {days} prochain jour*':
        '📅 *Plan, next {days} day*',
    'Rien de prévu. Demande-moi de planifier, ou lance /briefing.':
        'Nothing planned. Ask me to plan, or run /briefing.',
    'journée':
        'all day',
    'Séance':
        'Session',
    '🔋 *Forme*':
        '🔋 *Fitness*',
    '- Forme (CTL) : {value}':
        '- Fitness (CTL): {value}',
    '- Fatigue (ATL) : {value}':
        '- Fatigue (ATL): {value}',
    '- Fraîcheur (TSB) : {value} ({status})':
        '- Form (TSB): {value} ({status})',
    '- Ratio aigu/chronique : {value} ({status})':
        '- Acute/chronic ratio: {value} ({status})',
    '- Jours de repos sur 7 j : {days}':
        '- Rest days in the last 7: {days}',
    '📊 *Volume par semaine*':
        '📊 *Weekly volume*',
    'cette semaine':
        'this week',
    'sem. du {date}':
        'week of {date}',
    '- {week} : {km} km, {n} sorties':
        '- {week}: {km} km, {n} runs',
    '- {week} : {km} km, {n} sortie':
        '- {week}: {km} km, {n} run',
    '🏃 *Derniers runs*':
        '🏃 *Latest runs*',
    '🌤️ *Météo*':
        '🌤️ *Weather*',
    'Sur tes séances':
        'On your sessions',
    '🏃 *Sur tes séances* (créneau exact)':
        '🏃 *On your sessions* (exact slot)',
    '☀️ dégagé':
        '☀️ clear',
    '🌤️ peu nuageux':
        '🌤️ partly cloudy',
    '☁️ couvert':
        '☁️ overcast',
    '🌫️ brouillard':
        '🌫️ fog',
    '🌦️ bruine':
        '🌦️ drizzle',
    '🌧️ pluie':
        '🌧️ rain',
    '🌨️ neige':
        '🌨️ snow',
    '⛈️ orage':
        '⛈️ thunderstorm',
    'pluie {mm} mm':
        'rain {mm} mm',
    ', sec heure par heure':
        ', dry hour by hour',
    '{rain}, vent {wind} km/h':
        '{rain}, wind {wind} km/h',
    'indisponible':
        'unavailable',
    'non configurée':
        'not configured',
    ' (lieux : {places})':
        ' (places: {places})',
    'Sur tes séances (heure par heure, créneau exact) :':
        'On your sessions (hour by hour, exact slot):',
    'pluie':
        'rain',
    'chaleur':
        'heat',
    'vent':
        'wind',
    'verglas':
        'ice',
    '{temp}°C ressentis':
        'feels like {temp}°C',
    'rafales {gust} km/h':
        'gusts {gust} km/h',
    '{temp}°C, sol glissant possible':
        '{temp}°C, possibly slippery ground',
    'dans {n} j':
        'in {n} d',
    'pluie {prob}{mm} mm':
        'rain {prob}{mm} mm',
    'sec':
        'dry',
    ' (risque {prob} %)':
        ' (risk {prob} %)',
    'ressenti {temp}°C':
        'feels like {temp}°C',
    "RÈGLES (toujours appliquées, sauf demande explicite contraire de l'athlète)":
        'RULES (always applied, unless the athlete explicitly asks otherwise)',
    'PRÉFÉRENCES FORTES (appliquées sauf bonne raison, à expliquer)':
        "STRONG PREFERENCES (applied unless there's a good reason, to be explained)",
    "INDICATIONS (à prendre en compte quand c'est possible)":
        'HINTS (taken into account when possible)',
    "(rien pour l'instant)":
        '(nothing yet)',
    '(depuis {date})':
        '(since {date})',
    'sans date':
        'no date',
    'passé depuis {days} j':
        '{days} d ago',
    "aujourd'hui":
        'today',
    ' (~{weeks} sem.)':
        ' (~{weeks} wk)',
    'cible {target}':
        'target {target}',
    "⚠️ Attention, en vrai rien n'a changé dans ton agenda.":
        '⚠️ Heads up: nothing actually changed in your calendar.',
    "⚠️ J'ai pas réussi à ajouter « {event} » dans ton agenda. On réessaie ?":
        "⚠️ I couldn't add “{event}” to your calendar. Shall we try again?",
    "⚠️ J'ai pas réussi à modifier « {event} » dans ton agenda. On réessaie ?":
        "⚠️ I couldn't change “{event}” in your calendar. Shall we try again?",
    "⚠️ J'ai pas réussi à supprimer « {event} » dans ton agenda. On réessaie ?":
        "⚠️ I couldn't delete “{event}” from your calendar. Shall we try again?",
    "⚠️ J'ai dû m'arrêter en route, jette un œil à ton agenda pour vérifier.":
        '⚠️ I had to stop partway, take a look at your calendar to check.',
    "⚠️ J'ai eu un bug en route 🥲 Réessaie ?":
        '⚠️ I hit a bug along the way 🥲 Try again?',
    'FC moy {hr}':
        'avg HR {hr}',
    'Sortie':
        'Run',
    "🏃 *Salut, c'est Bob* 🤖\nÉcris-moi simplement : « décale ma sortie de samedi », « je suis crevé, allège demain », « planifie ma semaine »…\n\n*Infos instantanées* (sans IA, gratuites)\n/plan — séances prévues sur 7 jours (/plan 14 pour 14 jours)\n/load — charge d'entraînement (TSB, ratio A/C) et volume\n/runs — tes 5 derniers runs\n/weather — prévisions par lieu\n/goals — tes objectifs et le compte à rebours\n/memory — ce que je sais de toi\n\n*Avec le coach* (IA)\n/debrief — débrief de ton dernier run\n/review — bilan de la semaine : prévu vs fait, forme, semaine prochaine\n/shopping — liste de courses pour 7 jours selon tes objectifs sportifs et santé (/shopping 3 pour 3 jours), à cocher au magasin\n/list — réaffiche ta liste de courses en cours, à cocher\n/recipes — recettes faciles à préparer en boîtes avec ta liste (/recipes new pour en avoir d'autres)\n/briefing — briefing complet, ajuste le programme dans l'agenda\n/meme — un mème qui résume ta journée d'entraînement 😂\n/routes — 2 ou 3 boucles à la distance et au lieu de ta prochaine séance, là où tu ne croises personne : ni voitures, ni foule, ni vélos (carte + fichier GPX) ; /routes travail 8 nature pour choisir le lieu, la distance et le revêtement\n/newroute — une boucle jamais courue : /newroute 10 route bois de vincennes (distance, route / nature / mixte, lieu) ; ce qui manque, je te le demande\n\n/help — cette aide\n\nTu peux aussi m'envoyer des *vocaux* 🎙️. Quand je propose un changement, des boutons te permettent de l'appliquer.\n\n_Automatique : débrief et ressenti après chaque run. Bob n'écrit jamais le premier sinon._":
        "🏃 *Hi, it's Bob* 🤖\nJust text me: “move Saturday's run”, “I'm wiped, make tomorrow easier”, “plan my week”…\n\n*Instant info* (no AI, free)\n/plan — sessions planned for the next 7 days (/plan 14 for 14 days)\n/load — training load (TSB, A/C ratio) and volume\n/runs — your last 5 runs\n/weather — forecast per place\n/goals — your goals and the countdown\n/memory — what I know about you\n\n*With the coach* (AI)\n/debrief — debrief of your last run\n/review — weekly review: planned vs done, form, next week\n/shopping — shopping list for 7 days based on your sport and health goals (/shopping 3 for 3 days), to tick off in the store\n/list — shows your current shopping list again, to tick off\n/recipes — easy meal-prep recipes for your list (/recipes new for other ones)\n/briefing — full briefing, adjusts the plan in your calendar\n/meme — a meme that sums up your training day 😂\n/routes — 2 or 3 loops at your next session's distance and place, where you meet no one: no cars, no crowds, no bikes (map + GPX file); /routes work 8 trail to choose the place, distance and surface\n/newroute — a loop you've never run: /newroute 10 road central park (distance, road / trail / mixed, place); I'll ask for whatever is missing\n\n/help — this help\n\nYou can also send me *voice messages* 🎙️. When I suggest a change, buttons let you apply it.\n\n_Automatic: debrief and check-in after each run. Bob never writes first otherwise._",
}
