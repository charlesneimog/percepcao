local ModalMelody = pd.Class:new():register("p.modal.melody")
local bhack = require("bhack")

-- A mode is represented by its semitone scale and modal cadence chord.
-- cadence_degree is one-based (V = 5, bII = 2, etc.).
local MODES = {
	jonio = { scale = { 0, 2, 4, 5, 7, 9, 11 }, cadence_degree = 5 },
	dorico = { scale = { 0, 2, 3, 5, 7, 9, 10 }, cadence_degree = 4 },
	frigio = { scale = { 0, 1, 3, 5, 7, 8, 10 }, cadence_degree = 2 },
	lidio = { scale = { 0, 2, 4, 6, 7, 9, 11 }, cadence_degree = 2 },
	mixolidio = { scale = { 0, 2, 4, 5, 7, 9, 10 }, cadence_degree = 7 },
	eolio = { scale = { 0, 2, 3, 5, 7, 8, 10 }, cadence_degree = 7 },
	-- i degree is diminished because the Locrian fifth is flattened.
	locrio = { scale = { 0, 1, 3, 5, 6, 8, 10 }, cadence_degree = 2 },
}

local MODE_ALIASES = {
	ionian = "jonio",
	dorian = "dorico",
	phrygian = "frigio",
	fridio = "frigio", -- accepted because it is common in existing patches
	lydian = "lidio",
	mixolydian = "mixolidio",
	aeolian = "eolio",
	locrian = "locrio",
}

local LETTERS = { "C", "D", "E", "F", "G", "A", "B" }
local NATURAL_PC = { C = 0, D = 2, E = 4, F = 5, G = 7, A = 9, B = 11 }

local function first_atom(value)
	if type(value) == "table" then
		return value[1]
	end
	return value
end

local function normalize_mode(value)
	local name = tostring(first_atom(value) or ""):lower()
	-- Pd normally sends ASCII symbols, but accepting UTF-8 names here makes
	-- messages copied from Portuguese prose work as expected.
	name = name:gsub("ô", "o"):gsub("ó", "o"):gsub("í", "i")
	name = name:gsub("[^%a]", "")
	name = MODE_ALIASES[name] or name
	if MODES[name] then
		return name
	end
	return nil
end

local function parse_pitch(value)
	local text = tostring(first_atom(value) or "")
	local letter, accidental, octave = text:match("^%s*([A-Ga-g])([#b]?)(%-?%d+)%s*$")
	if not letter then
		return nil, "fundamental must be a pitch such as C4, D4, F#3 or Bb3"
	end
	letter = letter:upper()
	local alteration = accidental == "#" and 1 or (accidental == "b" and -1 or 0)
	local midi = (tonumber(octave) + 1) * 12 + NATURAL_PC[letter] + alteration
	return { letter = letter, accidental = accidental, octave = tonumber(octave), midi = midi }
end

local function signed_accidental(delta)
	if delta == 0 then
		return ""
	elseif delta == 1 then
		return "#"
	elseif delta == -1 then
		return "b"
	elseif delta == 2 then
		return "##"
	elseif delta == -2 then
		return "bb"
	end
	return nil
end

-- Spell by modal degree rather than by a chromatic sharp-only lookup.  Thus C
-- Phrygian produces Db (not C#), and C Locrian produces both Db and Gb.
local function spell_degree(root, mode, absolute_degree)
	local zero_degree = absolute_degree - 1
	local scale_index = (zero_degree % 7) + 1
	local degree_octave = math.floor(zero_degree / 7)
	local root_letter_index
	for i, letter in ipairs(LETTERS) do
		if letter == root.letter then
			root_letter_index = i
			break
		end
	end
	local letter_zero = (root_letter_index - 1) + zero_degree
	local letter = LETTERS[(letter_zero % 7) + 1]
	local letter_octave = root.octave + math.floor(letter_zero / 7)
	local target_midi = root.midi + mode.scale[scale_index] + 12 * degree_octave
	local natural_midi = (letter_octave + 1) * 12 + NATURAL_PC[letter]
	local accidental = signed_accidental(target_midi - natural_midi)
	if accidental == nil then
		-- This is only reachable for unusual theoretical roots.  Preserve a
		-- playable pitch even when conventional spelling needs triple signs.
		local sharp_names = { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" }
		return sharp_names[(target_midi % 12) + 1] .. tostring(math.floor(target_midi / 12) - 1), target_midi
	end
	return letter .. accidental .. tostring(letter_octave), target_midi
end

local function rhythm_number(entry)
	if type(entry) == "number" then
		return entry, false
	elseif type(entry) == "string" then
		local tied = entry:sub(-1) == "_"
		return tonumber(tied and entry:sub(1, -2) or entry), tied
	end
	return nil, false
end

local function rhythm_sum(entries)
	local result = 0
	for _, entry in ipairs(entries or {}) do
		if type(entry) == "table" and type(entry[2]) == "table" then
			result = result + math.abs(tonumber(entry[1]) or 0)
		else
			local value = rhythm_number(entry)
			result = result + math.abs(value or 0)
		end
	end
	return result
end

local function flatten_level(entries, start, duration, events, state, measure_index)
	local total = rhythm_sum(entries)
	if total <= 0 then
		return false, "rhythm level has zero duration"
	end
	local cursor = start
	for _, entry in ipairs(entries) do
		local span
		if type(entry) == "table" and type(entry[2]) == "table" then
			span = duration * math.abs(tonumber(entry[1]) or 0) / total
			local ok, err = flatten_level(entry[2], cursor, span, events, state, measure_index)
			if not ok then return false, err end
		else
			local value, tied = rhythm_number(entry)
			if value == nil then
				return false, "invalid rhythm-tree entry: " .. tostring(entry)
			end
			span = duration * math.abs(value) / total
			local is_rest = value < 0
			if is_rest then
				state.slots[measure_index][#state.slots[measure_index] + 1] = {
					kind = "rest", duration = span, tied = false,
				}
				state.pending_tie = false
			elseif state.pending_tie then
				-- bhack.voicebuilder reuses the previous pitch for this continuation
				-- and therefore does not consume a new item from the melody dddd.
				state.slots[measure_index][#state.slots[measure_index] + 1] = {
					kind = "continuation", duration = span, tied = tied,
				}
				state.pending_tie = tied
			else
				events[#events + 1] = {
					measure = measure_index,
					position = cursor,
					duration = span,
				}
				state.slots[measure_index][#state.slots[measure_index] + 1] = {
					kind = "attack", attack_index = #events, duration = span, tied = tied,
				}
				state.pending_tie = tied
			end
		end
		cursor = cursor + span
	end
	return true
end

local function analyze_tree(tree)
	if type(tree) ~= "table" or #tree == 0 then
		return nil, "rhythm tree must contain at least one measure"
	end
	local events, measures, slots = {}, {}, {}
	local current_time_signature = { 4, 4 }
	local state = { pending_tie = false, slots = slots }
	for measure_index, measure_spec in ipairs(tree) do
		if type(measure_spec) ~= "table" or #measure_spec == 0 then
			return nil, "measure " .. measure_index .. " is invalid"
		end
		local rhythms
		if type(measure_spec[1]) == "table" and #measure_spec == 2 and type(measure_spec[2]) == "table" then
			current_time_signature = { tonumber(measure_spec[1][1]), tonumber(measure_spec[1][2]) }
			rhythms = measure_spec[2]
		else
			rhythms = measure_spec[1]
		end
		if not current_time_signature[1] or not current_time_signature[2] or current_time_signature[2] == 0 then
			return nil, "measure " .. measure_index .. " has an invalid time signature"
		end
		if type(rhythms) ~= "table" then
			return nil, "measure " .. measure_index .. " has no rhythm list"
		end
		measures[measure_index] = { time_signature = current_time_signature }
		slots[measure_index] = {}
		local ok, err = flatten_level(rhythms, 0, 1, events, state, measure_index)
		if not ok then return nil, "measure " .. measure_index .. ": " .. err end
	end
	if #events == 0 then
		return nil, "rhythm tree contains no sounded attacks"
	end
	return { events = events, measures = measures, slots = slots, tree = tree, measure_count = #tree }
end

local function is_strong_beat(event, measure)
	local numerator, denominator = measure.time_signature[1], measure.time_signature[2]
	local position = event.position % 1
	if math.abs(position) < 1e-7 then return true end
	-- The secondary accent is halfway through even meters with more than two
	-- beats/groups: beat 3 in 4/4, the second dotted beat in 6/8, etc.  Beats 2
	-- and 4 in 4/4 remain weak and may therefore carry modal passing tones.
	local groups = (denominator == 8 and numerator > 3 and numerator % 3 == 0) and (numerator / 3) or numerator
	return groups > 2 and groups % 2 == 0 and math.abs(position - 0.5) < 1e-7
end

local function triad_degrees(root_degree)
	return { root_degree, root_degree + 2, root_degree + 4 }
end

local function pitch_candidates(root, mode, allowed_degrees, previous_midi)
	local candidates = {}
	local low = root.midi - 5
	local high = root.midi + 12
	for octave = -2, 2 do
		for _, degree in ipairs(allowed_degrees) do
			local absolute_degree = degree + octave * 7
			local name, midi = spell_degree(root, mode, absolute_degree)
			-- Keep the result in a compact, comfortable octave around the supplied root.
			if midi >= low and midi <= high then
				local leap = previous_midi and math.abs(midi - previous_midi) or 0
				candidates[#candidates + 1] = { name = name, midi = midi, degree = absolute_degree, leap = leap }
			end
		end
	end
	return candidates
end

local function leap_budget(values)
	if values == nil then return nil end
	local budget = {}
	for _, value in ipairs(values) do
		budget[value] = (budget[value] or 0) + 1
	end
	return budget
end

local function leap_is_available(leap, budget)
	-- Unisons, semitones and tones are neighbouring motion, not jumps.
	if leap <= 2 then return true end
	-- nil preserves the original unrestricted API for callers which do not use
	-- inlet 4.  Object instances always supply an explicit budget.
	if budget == nil then return leap <= 7 end
	return (budget[leap] or 0) > 0
end

local function consume_leap(leap, budget)
	if budget ~= nil and leap > 2 then
		budget[leap] = budget[leap] - 1
	end
end

local function copy_budget(budget)
	if budget == nil then return nil end
	local copy = {}
	for interval, count in pairs(budget) do copy[interval] = count end
	return copy
end

local function candidate_score(candidate, previous_midi, contour, target_midi, previous_previous_midi)
	local score = candidate.leap * 2 + math.abs(candidate.midi - target_midi) * 0.35
	if candidate.leap <= 2 then score = score - 2 end
	-- Repeated pitches and two-note loops make the generated solfege feel
	-- mechanical.  Keep them possible only when the harmonic and interval
	-- constraints leave no alternative.
	if previous_midi and candidate.midi == previous_midi then score = score + 30 end
	if previous_previous_midi and candidate.midi == previous_previous_midi then score = score + 9 end
	if previous_previous_midi and candidate.midi == previous_midi and previous_midi == previous_previous_midi then
		score = score + 6
	end
	if previous_midi then
		if contour == "up" and candidate.midi < previous_midi then score = score + 1.25 end
		if contour == "down" and candidate.midi > previous_midi then score = score + 1.25 end
	end
	return score + math.random() * 0.4
end

local function final_measure_target(root, mode, position)
	-- An arch in scale degrees gives the last measure a clear direction instead
	-- of hovering between the tonic and its leading/subtonic neighbour:
	-- 8 attacks, for example, aim at 1-2-3-4-5-4-3-2-1.
	local degree
	if position <= 0.5 then
		degree = 1 + math.floor(position * 8 + 0.5)
	else
		degree = 1 + math.floor((1 - position) * 8 + 0.5)
	end
	degree = math.max(1, math.min(5, degree))
	local _, midi = spell_degree(root, mode, degree)
	return midi
end

local RHYTHM_CELLS = {
	{ span = 1, tree = { 1, { 1, 1 } } },
		{ span = 1, tree = { 1, { 1, 1 } } },

	--{ span = 1, tree = { 1, { 3, 1 } } },
	{ span = 1, tree = { 1, { 2, 1, 1 } } },
	{ span = 2, tree = { 2, { 1 } } },
	{ span = 4, tree = { 4, { 1 } } },

}

local function deep_copy(value)
	if type(value) ~= "table" then return value end
	local result = {}
	for key, item in pairs(value) do result[key] = deep_copy(item) end
	return result
end

local function build_internal_tree(measure_count)
	local tree = {}
	for measure = 1, measure_count do
		if measure == measure_count then
			-- The resolution is a single tonic attack on beat 1, sustained to
			-- the end of the final 4/4 measure.
			tree[measure] = { { 4, 4 }, { deep_copy(RHYTHM_CELLS[5].tree) } }
		else
			local rhythms = {}
			local beats_left = 4
			while beats_left > 0 do
				local beat_position = 4 - beats_left
				local choices = {}
				for _, cell in ipairs(RHYTHM_CELLS) do
					local aligned = cell.span == 1
						or (cell.span == 2 and (beat_position == 0 or beat_position == 2))
						or (cell.span == 4 and beat_position == 0)
					if aligned and cell.span <= beats_left then choices[#choices + 1] = cell end
				end
				local cell = choices[math.random(1, #choices)]
				rhythms[#rhythms + 1] = deep_copy(cell.tree)
				beats_left = beats_left - cell.span
			end
			tree[measure] = { { 4, 4 }, rhythms }
		end
	end
	return tree
end

local function build_harmonic_plan(measure_count, mode)
	local plan = {}
	-- Alternate tonic and characteristic harmony, then guarantee the modal
	-- cadence characteristic -> tonic.  With G Lydian this gives:
	-- 3: G|A|G, 4: G|A|A|G, 5: G|A|G|A|G, 6: G|A|G|A|A|G.
	for measure = 1, measure_count do
		if measure == measure_count then
			plan[measure] = { 1 }
		elseif measure == measure_count - 1 then
			plan[measure] = { mode.cadence_degree }
		else
			plan[measure] = { (measure % 2 == 1) and 1 or mode.cadence_degree }
		end
	end
	return plan
end

local function harmony_for_event(event, analysis, mode)
	local plan = analysis.harmonic_plan or build_harmonic_plan(analysis.measure_count, mode)
	local measure_chords = plan[event.measure]
	if #measure_chords == 1 then return measure_chords[1] end
	local chord_index = math.min(#measure_chords, math.floor(event.position * #measure_chords) + 1)
	return measure_chords[chord_index]
end

local function generate_melody(tree, mode_name, root, allowed_leaps)
	local analysis, err = analyze_tree(tree)
	if not analysis then return nil, err end
	local mode = MODES[mode_name]
	analysis.harmonic_plan = build_harmonic_plan(analysis.measure_count, mode)
	local states = { {
		notes = {},
		budget = leap_budget(allowed_leaps),
		score = 0,
		previous = nil,
		previous_previous = nil,
		characteristic_announced = false,
	} }
	-- Keep enough alternative paths to preserve scarce leap tokens for later
	-- harmonic transitions and the cadence.
	local maximum_states = 2048
	local starting_degree
	for index, event in ipairs(analysis.events) do
		local is_last = index == #analysis.events
		local in_final_measure = event.measure == analysis.measure_count
		local strong = is_strong_beat(event, analysis.measures[event.measure])
		local harmony_degree = harmony_for_event(event, analysis, mode)
		local allowed = strong and triad_degrees(harmony_degree) or { 1, 2, 3, 4, 5, 6, 7 }
		if index == 1 then
			starting_degree = allowed[math.random(1, #allowed)]
		end
		local progress = (#analysis.events == 1) and 1 or ((index - 1) / (#analysis.events - 1))
		local contour = progress < 0.5 and "up" or "down"
		local target
		if in_final_measure then
			contour = event.position < 0.5 and "up" or "down"
			if is_last then
				target = root.midi
			elseif index == #analysis.events - 1 then
				local _, supertonic_midi = spell_degree(root, mode, 2)
				target = supertonic_midi
			else
				target = final_measure_target(root, mode, event.position)
			end
		else
			local arch = progress < 0.5 and progress * 2 or (1 - progress) * 2
			target = root.midi + 7 * arch
		end

		local next_states = {}
		for _, state in ipairs(states) do
			local candidates
			if is_last then
				local name, midi = spell_degree(root, mode, 1)
				candidates = { { name = name, midi = midi, degree = 1 } }
			elseif index == 1 then
				candidates = pitch_candidates(root, mode, { starting_degree }, state.previous)
			else
				candidates = pitch_candidates(root, mode, allowed, state.previous)
			end
			for _, candidate in ipairs(candidates) do
				candidate.leap = state.previous and math.abs(candidate.midi - state.previous) or 0
				if leap_is_available(candidate.leap, state.budget) then
					local next_budget = copy_budget(state.budget)
					consume_leap(candidate.leap, next_budget)
					local notes = {}
					for note_index, note in ipairs(state.notes) do notes[note_index] = note end
					notes[#notes + 1] = { candidate.name }
					local announced = state.characteristic_announced
					local extra = candidate_score(candidate, state.previous, contour, target, state.previous_previous)
					if in_final_measure and index == #analysis.events - 1 and (candidate.midi % 12) == (root.midi % 12) then
						extra = extra + 50
					end
					if strong and harmony_degree == mode.cadence_degree and not announced then
						local _, characteristic_midi = spell_degree(root, mode, harmony_degree)
						if (candidate.midi % 12) == (characteristic_midi % 12) then
							extra = extra - 5
							announced = true
						end
					end
					next_states[#next_states + 1] = {
						notes = notes,
						budget = next_budget,
						score = state.score + extra,
						previous = candidate.midi,
						previous_previous = state.previous,
						characteristic_announced = announced,
					}
				end
			end
		end
		if #next_states == 0 then
			return nil, string.format("no valid path at event %d for the interval budget from inlet 4", index)
		end
		table.sort(next_states, function(a, b) return a.score < b.score end)
		while #next_states > maximum_states do table.remove(next_states) end
		states = next_states
	end
	table.sort(states, function(a, b) return a.score < b.score end)
	return states[1].notes
end

local function greatest_common_divisor(a, b)
	a, b = math.abs(a), math.abs(b)
	while b ~= 0 do a, b = b, a % b end
	return a
end

local function collapse_repetitions(analysis, melody)
	local collapsed_melody, collapsed_tree = {}, {}
	for measure_index = 1, analysis.measure_count do
		local measure_notes = {}
		local has_rest = false
		for _, slot in ipairs(analysis.slots[measure_index]) do
			if slot.kind == "rest" then
				has_rest = true
			elseif slot.kind == "attack" then
				measure_notes[#measure_notes + 1] = melody[slot.attack_index][1]
			end
		end
		local all_equal = #measure_notes > 0 and not has_rest
		for i = 2, #measure_notes do
			if measure_notes[i] ~= measure_notes[1] then all_equal = false break end
		end
		if all_equal then
			collapsed_melody[#collapsed_melody + 1] = { measure_notes[1] }
			collapsed_tree[measure_index] = { { 4, 4 }, { { 4, { 1 } } } }
		else
			for _, pitch in ipairs(measure_notes) do
				collapsed_melody[#collapsed_melody + 1] = { pitch }
			end
			collapsed_tree[measure_index] = deep_copy(analysis.tree[measure_index])
		end
	end
	return collapsed_melody, collapsed_tree
end

ModalMelody.MODES = MODES
ModalMelody.normalize_mode = normalize_mode
ModalMelody.parse_pitch = parse_pitch
ModalMelody.analyze_tree = analyze_tree
ModalMelody.generate_melody = generate_melody
ModalMelody.collapse_repetitions = collapse_repetitions
ModalMelody.is_strong_beat = is_strong_beat
ModalMelody.harmony_for_event = harmony_for_event
ModalMelody.build_internal_tree = build_internal_tree
ModalMelody.build_harmonic_plan = build_harmonic_plan

function ModalMelody:initialize(_, args)
	self.inlets = 4
	self.outlets = 2
	self.mode_name = "jonio"
	self.root = assert(parse_pitch("C4"))
	self.measure_count = 4
	self.bpm = 80
	self.allowed_leaps = {}
	args = args or {}
	if args[1] ~= nil then
		local mode_name = normalize_mode(args[1])
		if not mode_name then
			self:error("[p.modal.melody] unknown mode: " .. tostring(args[1]))
			return false
		end
		self.mode_name = mode_name
	end
	if args[2] ~= nil then
		local root, err = parse_pitch(args[2])
		if not root then
			self:error("[p.modal.melody] " .. err)
			return false
		end
		self.root = root
	end
	return true
end

function ModalMelody:emit()
	local rhythm_tree = build_internal_tree(self.measure_count)
	local analysis, analysis_err = analyze_tree(rhythm_tree)
	if not analysis then
		self:error("[p.modal.melody] " .. analysis_err)
		return
	end
	local melody, err = generate_melody(rhythm_tree, self.mode_name, self.root, self.allowed_leaps)
	if not melody then
		self:error("[p.modal.melody] " .. err)
		return
	end
	local collapsed_melody, collapsed_tree = collapse_repetitions(analysis, melody)
	-- Outlet numbering now mirrors bhack.voicebuilder: rhythm -> inlet 1 and
	-- melody -> inlet 2.  Emit the melody first because the rhythm inlet is hot.
	bhack.dddd:new_from_table(self, collapsed_melody):output(2)
	self:outlet(1, "bpm", { self.bpm })
	bhack.dddd:new_from_table(self, collapsed_tree):output(1)
end

function ModalMelody:in_1_dddd(atoms)
	self:error("[p.modal.melody] inlet 1 now expects a measure count, not a rhythm-tree dddd")
end

function ModalMelody:in_1_float(value)
	local count = tonumber(first_atom(value))
	if count == nil or count ~= math.floor(count) or count < 2 then
		self:error("[p.modal.melody] measure count must be an integer of at least 2")
		return
	end
	self.measure_count = count
	self:emit()
end

function ModalMelody:in_1_bang()
	self:emit()
end

function ModalMelody:set_mode(value)
	local mode_name = normalize_mode(value)
	if not mode_name then
		self:error("[p.modal.melody] mode must be jonio, dorico, frigio/fridio, lidio, mixolidio, eolio or locrio")
		return
	end
	self.mode_name = mode_name
end

function ModalMelody:in_2_symbol(value) self:set_mode(value) end
function ModalMelody:in_2_list(value) self:set_mode(value) end
function ModalMelody:in_2(selector, _) self:set_mode(selector) end

function ModalMelody:set_root(value)
	local root, err = parse_pitch(value)
	if not root then
		self:error("[p.modal.melody] " .. err)
		return
	end
	self.root = root
end

function ModalMelody:in_3_symbol(value) self:set_root(value) end
function ModalMelody:in_3_list(value) self:set_root(value) end
function ModalMelody:in_3(selector, _) self:set_root(selector) end

function ModalMelody:set_allowed_leaps(values)
	if type(values) ~= "table" then values = { values } end
	local parsed = {}
	for index, value in ipairs(values) do
		local interval = tonumber(value)
		if interval == nil or interval < 3 or interval ~= math.floor(interval) then
			self:error(string.format("[p.modal.melody] inlet 4 item %d must be an integer interval of at least 3 semitones", index))
			return
		end
		parsed[#parsed + 1] = interval
	end
	self.allowed_leaps = parsed
end

function ModalMelody:in_4_float(value) self:set_allowed_leaps(value) end
function ModalMelody:in_4_list(values) self:set_allowed_leaps(values) end
function ModalMelody:in_4_bang() self.allowed_leaps = {} end

function ModalMelody:in_1_seed(atoms)
	local seed = tonumber(first_atom(atoms))
	if not seed then
		self:error("[p.modal.melody] seed expects a number")
		return
	end
	math.randomseed(seed)
end

function ModalMelody:in_1_reload()
	self:dofilex(self._scriptname)
end
