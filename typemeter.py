import time
import keyboard
import random

words_database_easy = [
    "over", "large", "just", "few", "only", "come", "all", "tell",
    "say", "lead", "they", "see", "so", "face", "home", "fact",
    "act", "well", "so", "turn", "thing", "we", "life", "because", "night",
    "run", "play", "is", "not", "a", "game", "how", "what", "when", "of",
    "about", "about", "the", "be", "of", "and", "a", "to", "in", "he", "have", "it", 
    "that", "for", "they", "with", "as", "not", "on", "she", "at", "by", "this", "we", 
    "you", "do", "but", "from", "or", "which", "one", "would", "all", "will", "there", "say",
    "who", "make", "when", "can", "more", "if", "no", "man", "out", "other", "so",
    "what", "time", "up", "go", "about", "than", "into", "could", "state", "only",
    "new", "year", "some", "take", "come", "these", "know", "see", "use", "get",
    "like", "then", "first", "any", "work", "now", "may", "such", "give", "over",
    "think", "most", "even", "find", "day", "also", "after", "way", "many", "must",
    "look", "before", "great", "back", "through", "long", "where", "much", "should",
    "well", "people", "down", "own", "just", "because", "good", "each", "those",
    "feel", "seem", "how", "high", "too", "place", "little", "world", "very", "still",
    "nation", "hand", "old", "life", "tell", "write", "become", "under", "last",
    "right", "move", "thing", "general", "school", "never", "same", "another", "begin",
    "while", "number", "part", "turn", "real", "leave", "might", "want", "point",
    "form", "off", "child", "few", "small", "since", "against", "ask", "late", "home",
    "interest", "large", "person", "end", "open", "public", "follow", "during", "present",
    "without", "again", "hold", "govern", "around", "possible", "head", "consider",
    "word", "program", "problem", "however", "lead", "system", "set", "order", "eye",
    "plan", "run", "keep", "face", "fact", "group", "play", "stand", "increase", "early",
    "course", "change", "help", "line", "a",
]

words_database_medium = [
    "abundant", "access", "achieve", "gather", "difficulty", "support", "unclear", "worried",
    "hard", "clear", "confident", "blend", "confirm", "kind", "rules", "friendship",
    "trigger", "merge", "complicated", "together", "remember", "complete", "agree", "friendly",
    "talk", "friendly", "tricky", "together", "complicated", "growing", "harmful", "criticize",
    "show", "behavior", "copy", "hardworking", "dislike", "explain", "spread", "different",
    "detail", "wellspoken", "understanding", "try", "mystery", "count", "shortlived", "unclear",
    "knowledgeable", "polite", "worsen", "typify", "speedup", "explain", "praise", "joking",
    "possible", "change", "courage", "encourage", "save", "sociable", "random", "order",
    "suggestion", "make", "unintentional", "doesnt", "native",
    "random", "honest", "look", "indecisive", "sidebyside", "grieve", "lavish", "lazy",
    "generous", "obvious", "wander", "careful", "average", "calm", "repetitive", "many",
    "care", "unaware", "oldfashioned", "threatening", "luxurious", "traditional", "contradiction", "observant",
    "continue", "relevant", "realistic", "risky", "trouble", "common", "impressive", "skilled",
    "plentiful", "creative", "prosperous", "wise", "strong", "dilemma", "hungry", "scold",
    "make", "repeat", "let", "bounce", "respect", "persuasive", "basic", "wise",
    "examine", "fortunate", "doubtful", "occasional", "stoic", "secretive", "susceptible", "silent",
    "touchable", "weak", "everywhere", "agreed", "never", "unjustified", "respected", "able",
    "alert", "prove", "skilled", "easily", "funny", "enthusiastic",
    "over", "large", "just", "few", "only", "come", "all", "tell",
    "say", "lead", "they", "see", "so", "face", "home", "fact",
    "act", "well", "so", "turn", "thing", "we", "life", "because", "night",
    "run", "play", "is", "not", "a", "game", "how", "what", "when", "of",
    "about", "about", "the", "be", "of", "and", "a", "to", "in", "he", "have", "it", 
    "that", "for", "they", "with", "as", "not", "on", "she", "at", "by", "this", "we", 
    "you", "do", "but", "from", "or", "which", "one", "would", "all", "will", "there", "say",
    "who", "make", "when", "can", "more", "if", "no", "man", "out", "other", "so",
    "what", "time", "up", "go", "about", "than", "into", "could", "state", "only",
    "new", "year", "some", "take", "come", "these", "know", "see", "use", "get",
    "like", "then", "first", "any", "work", "now", "may", "such", "give", "over",
    "think", "most", "even", "find", "day", "also", "after", "way", "many", "must",
    "look", "before", "great", "back", "through", "long", "where", "much", "should",
    "well", "people", "down", "own", "just", "because", "good", "each", "those",
    "feel", "seem", "how", "high", "too", "place", "little", "world", "very", "still",
    "nation", "hand", "old", "life", "tell", "write", "become", "under", "last",
    "right", "move",
    "thing", "general", "school", "never", "same", "another", "begin",
    "while", "number", "part", "turn", "real", "leave", "might", "want", "point",
    "form", "off", "child", "few", "small", "since", "against", "ask", "late", "home",
    "interest", "large", "person", "end", "open", "public", "follow", "during", "present",
    "without", "again", "hold", "govern", "around", "possible", "head", "consider",
    "word", "program", "problem", "however", "lead", "system", "set", "order", "eye",
    "plan", "run", "keep", "face", "fact", "group", "play", "stand", "increase", "early",
    "course", "change", "help", "line", "a",
]

words_database_hard = [
    "abhorrent", "acrimonious", "affluent", "ambivalent", "anachronistic", "antagonize", "apocryphal", "auspicious",
    "belligerent", "cacophony", "capitulate", "circumlocution", "cognizant", "deleterious", "desultory", "dichotomy",
    "disparage", "ebullient", "efficacious", "equanimity", "exacerbate", "exonerate", "extemporaneous", "facetious",
    "fastidious", "flagrant", "garrulous", "gregarious", "hackneyed", "idiosyncratic", "indignant", "inimical",
    "insidious", "intransigent", "inveterate", "juxtaposition", "laconic", "lugubrious", "magnanimous", "malfeasance",
    "mendacious", "nefarious", "obfuscate", "ostentatious", "paradigm", "pariah", "pensive", "pernicious",
    "pertinacious", "plethora", "predilection", "prevaricate", "proclivity", "propensity", "pulchritude", "querulous",
    "quixotic", "recalcitrant", "recidivism", "recondite", "redolent", "replete", "repudiate", "sagacious",
    "salient", "sanguine", "scurrilous", "solipsistic", "stalwart", "supercilious", "sycophant", "tantamount",
    "tenuous", "trenchant", "ubiquitous", "umbrage", "unctuous", "unilateral", "usurp", "vacillate",
    "venerable", "vicissitude", "vitriolic", "vociferous", "wheedle", "winsome", "zealot", "zeitgeist",
    "over", "large", "just", "few", "only", "come", "all", "tell",
    "say", "lead", "they", "see", "so", "face", "home", "fact",
    "act", "well", "so", "turn", "thing", "we", "life", "because", "night",
    "run", "play", "is", "not", "a", "game", "how", "what", "when", "of",
    "about", "about", "the", "be", "of", "and", "a", "to", "in", "he", "have", "it", 
    "that", "for", "they", "with", "as", "not", "on", "she", "at", "by", "this", "we", 
    "you", "do", "but", "from", "or", "which", "one", "would", "all", "will", "there", "say",
    "who", "make", "when", "can", "more", "if", "no", "man", "out", "other", "so",
    "what", "time", "up", "go", "about", "than", "into", "could", "state", "only",
    "new", "year", "some", "take", "come", "these", "know", "see", "use", "get",
    "like", "then", "first", "any", "work", "now", "may", "such", "give", "over",
    "think", "most", "even", "find", "day", "also", "after", "way", "many", "must",
    "look", "before", "great", "back", "through", "long", "where", "much", "should",
    "well", "people", "down", "own", "just", "because", "good", "each", "those",
    "feel", "seem", "how", "high", "too", "place", "little", "world", "very", "still",
    "nation", "hand", "old", "life", "tell", "write", "become", "under", "last",
    "right", "move",
    "thing", "general", "school", "never", "same", "another", "begin",
    "while", "number", "part", "turn", "real", "leave", "might", "want", "point",
    "form", "off", "child", "few", "small", "since", "against", "ask", "late", "home",
    "interest", "large", "person", "end", "open", "public", "follow", "during", "present",
    "without", "again", "hold", "govern", "around", "possible", "head", "consider",
    "word", "program", "problem", "however", "lead", "system", "set", "order", "eye",
    "plan", "run", "keep", "face", "fact", "group", "play", "stand", "increase", "early",
    "course", "change", "help", "line", "a",
]


print(" _____                 __  __      _")
print("|_   _|   _ _ __   ___|  \\/  | ___| |_ ___ _ __")
print("  | || | | | '_ \\ / _ \\ |\\/| |/ _ \\ __/ _ \\ '__|")
print("  | || |_| | |_) |  __/ |  | |  __/ ||  __/ |")
print("  |_| \\__, | .__/ \\___|_|  |_|\\___|\\__\\___|_|")
print("      |___/|_|")


while True:
    permission = input("Do you want to play the game? \n 1. yes \n 2. no \n")
    permission = permission.lower()
    if permission == 'yes' or permission == '1':
        while(True):
            print("Enter the difficulty you want :\n 1. Easy \n 2. Medium \n 3. Hard")
            difficulty = input()
            difficulty = difficulty.lower()
            if difficulty == '1' or difficulty == 'easy':
                words_database = words_database_easy
                break
            elif difficulty == '2' or difficulty == 'medium':
                words_database = words_database_medium
                break
            elif difficulty == '3' or difficulty == 'hard':
                words_database = words_database_hard
                break
            else:
                print("Enter the valid difficulty as shown either in number or in words")

        set1 = set(words_database)
        words_database = list(set1)

        # print(words_database)

        num = int(input("Enter the number of words you want in the sentence "))

        sentence_list = []
        for i in range(num):
            weird = random.randint(0, len(words_database)-1)
            sentence_list.append(words_database[weird]) 
            del words_database[weird]
        string = " ".join(sentence_list)
        example = list(string)
        print(string)

        keys_to_monitor = [
            'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
            'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
            '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
            'space', 'enter', 'shift', 'ctrl', 'alt', 'tab', 'esc',
            'up', 'down', 'left', 'right',
            'backspace', 'delete', 'insert', 'home', 'end', 'page up', 'page down',
            'caps lock', 'num lock', 'scroll lock',
            'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
            'print screen', 'pause',
            '`', '-', '=', '[', ']', '\\', ';', "'", ',', '.', '/'
        ]

        attempt_list = []
        while True:
            try:
                for key in keys_to_monitor:
                    if keyboard.is_pressed(key):
                        # print("A key is pressed!")
                        start_time = time.time()
                        break
            finally:
                if 'start_time' in locals():
                    break

        attempt_str = input()
        end_time = time.time()

        for chr in attempt_str:
            attempt_list.append(chr)
        attempt_string = "".join(attempt_list)
        #print(attempt_string)

        actual_words = string.split()
        actual_words_count = len(actual_words)
        attempted_words = attempt_string.split()
        attempted_words_count = len(attempted_words)
        min_length = min(actual_words_count, attempted_words_count)

        correct_count = 0
        for i in range(min_length):
            if(actual_words[i] == attempted_words[i]):
                correct_count+=1


        mistake = 0
        i = 0

        while(i<len(example)):
            if(i<len(attempt_list)):
                    if(example[i] != attempt_list[i]):
                        mistake+=1
            else:
                break
            i+=1

        if(i<len(attempt_list)):
            mistake = mistake + (len(attempt_list)-i)
        #print(i)
        mistake = mistake + (len(example) - i)

        time_taken = end_time - start_time
        minute = time_taken/60
        #print("The number of mistakes are", mistake)
        print("\n")
        print("The time taken is", time_taken,"seconds")

        accuracy = ((len(example) - mistake)/len(example))*100
        if(accuracy<0):
            accuracy = -accuracy
        correct_chars = sum(1 for e_c, a_c in zip(example, attempt_list) if e_c == a_c)
        raw_wpm = (len(attempt_list) / 5) / minute if minute > 0 else 0
        wpm = (correct_chars / 5) / minute if minute > 0 else 0

        print("The accuracy is", accuracy,"%")
        print("The wpm is", wpm)
        print("The raw wpm is", raw_wpm)
    elif permission == 'no' or permission == '2':
        print(" ________  __    __      ______      _____     __  __   __   _______   ")
        print("|__    __||  |  |  |    /  __  \\    |     \\   |  ||  | /  / /  _____|  ")
        print("   |  |   |  |__|  |   /  /__\\  \\   |  |\\  \\  |  ||  |/  / |  |___     ")
        print("   |  |   |   __   |  /  ______  \\  |  | \\  \\ |  ||     |   \\____  \\   ")
        print("   |  |   |  |  |  | /  /      \\  \\ |  |  \\  \\|  ||  |\\  \\  ____/  |  ")
        print("   |__|   |__|  |__|/__/        \\__\\|__|   \\_____||__| \\__\\|______/   ")

        print(" ")
        print("")
        print("                        Visit again to play!!                                   ")
        print("")
        print("")
        break
    else:
        print("Please enter your answer correctly either in numbers or in words!!")