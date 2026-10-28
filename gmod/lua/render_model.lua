-- Render one live model to an image without moving the player camera.
local sequence = 0

return function(entity, options, completed)
    assert(CLIENT, 'Run model rendering on the client')
    assert(IsValid(entity), 'Select a valid model entity')
    options = options or {}
    assert(isvector(options.origin) and isvector(options.target), 'Specify the render origin and target')
    local name = options.name or 'model'
    assert(name:match('^[%w_-]+$'), 'Use a simple output name')
    local size = options.size or 1024
    assert(size == 512 or size == 1024 or size == 2048, 'Unsupported image size')
    local fov = options.fov or 40
    assert(isnumber(fov) and fov >= 10 and fov <= 100, 'Invalid field of view')
    local directory = 'characolle_port_checks'
    local path = directory .. '/' .. name .. '.png'
    assert(not file.Exists(path, 'DATA'), 'Render output already exists')
    sequence = sequence + 1
    local key = 'characolle_model_render_' .. tostring(SysTime()) .. '_' .. sequence
    local target = GetRenderTarget('characolle_model_render_' .. size, size, size)
    local inspect = options.inspect

    timer.Create(key, 20, 1, function()
        hook.Remove('PostRender', key)
        local result = {model = IsValid(entity) and entity:GetModel() or false, path = path,
            observed_at = os.time(), rendered = false, error = 'No render frame received within 20 seconds'}
        file.CreateDir(directory)
        file.Write(directory .. '/' .. name .. '.json', util.TableToJSON(result, true))
        if completed then completed(result) end
    end)

    hook.Add('PostRender', key, function()
        hook.Remove('PostRender', key)
        timer.Remove(key)
        local result = {model = IsValid(entity) and entity:GetModel() or false, path = path,
            observed_at = os.time(), width = size, height = size, rendered = false}
        local targetStarted, cameraStarted = false, false
        local hidden = IsValid(entity) and entity:GetNoDraw() or false
        local ok, message = xpcall(function()
            assert(IsValid(entity), 'Model entity was removed before rendering')
            entity:SetNoDraw(false)
            entity:SetupBones()
            if inspect then result.inspection = inspect(entity) end
            render.PushRenderTarget(target)
            targetStarted = true
            render.Clear(224, 228, 234, 255, true, true)
            cam.Start3D(options.origin, (options.target - options.origin):Angle(), fov,
                0, 0, size, size, 0.1, 8192)
            cameraStarted = true
            render.SuppressEngineLighting(true)
            render.ResetModelLighting(1, 1, 1)
            render.SetColorModulation(1, 1, 1)
            render.SetBlend(1)
            entity:DrawModel()
            cam.End3D()
            cameraStarted = false
            render.SuppressEngineLighting(false)
            local data = render.Capture({format = 'png', x = 0, y = 0, w = size, h = size, alpha = false})
            assert(data and #data > 0, 'Render capture unavailable; the game menu may be open')
            file.CreateDir(directory)
            file.Write(path, data)
            result.rendered = true
            result.bytes = #data
        end, debug.traceback)
        if cameraStarted then cam.End3D() end
        render.SuppressEngineLighting(false)
        render.ResetModelLighting(0, 0, 0)
        render.SetColorModulation(1, 1, 1)
        render.SetBlend(1)
        if targetStarted then render.PopRenderTarget() end
        if IsValid(entity) then entity:SetNoDraw(hidden) end
        result.draw_state_restored = not IsValid(entity) or entity:GetNoDraw() == hidden
        if not ok then result.error = message end
        file.CreateDir(directory)
        file.Write(directory .. '/' .. name .. '.json', util.TableToJSON(result, true))
        if completed then completed(result) end
    end)
    return path
end
