local textdisplay = pd.Class:new():register("textdisplay")

function textdisplay:initialize(name, args)
	self.inlets = 1
	self.outlets = 0
	self.fontsize = tonumber(args[1]) or 12
	self.padding = 4
	self.text = ""

	self:set_size(24, self.fontsize + self.padding * 2)
	return true
end

function textdisplay:set_text(text)
	self.text = tostring(text)

	local width = math.max(24, math.ceil(#self.text * self.fontsize * 0.65 + self.padding * 2))

	self:set_size(width, self.fontsize + self.padding * 2)
	self:repaint()
end

function textdisplay:in_1_symbol(s)
	self:set_text(s)
end

function textdisplay:in_1_float(n)
	self:set_text(n)
end

function textdisplay:in_1_list(atoms)
	self:set_text(table.concat(atoms, " "))
end

function textdisplay:in_1_anything(sel, atoms)
	local parts = { sel }
	for i = 1, #atoms do
		parts[#parts + 1] = tostring(atoms[i])
	end
	self:set_text(table.concat(parts, " "))
end

function textdisplay:in_1_bang()
	self.text = ""
	self:repaint()
end

function textdisplay:paint(g)
	local w, h = self:get_size()

	-- Background
	g:set_color(255, 255, 255)
	g:fill_all()

	g:set_color(0, 0, 0)
	-- Text
	if self.text ~= "" then
		g:draw_text(self.text, self.padding, self.padding, w - self.padding * 2, self.fontsize)
	end
end
