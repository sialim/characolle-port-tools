-- Client-side inspection of a loaded model without changing its pose or bodygroups.
local function vector(value)
    return value and {value.x, value.y, value.z} or nil
end

return function(entity)
    assert(CLIENT, 'Run model inspection on the client')
    assert(IsValid(entity), 'Select a valid model entity')
    entity:SetupBones()
    local report = {
        model = entity:GetModel(), entity_index = entity:EntIndex(),
        observed_at = os.time(), bones = {}, materials = {}, flexes = {}, bodygroups = {},
        material_errors = 0
    }
    for _,group in ipairs(entity:GetBodyGroups()) do
        report.bodygroups[#report.bodygroups + 1] = {
            id = group.id, name = group.name, models = group.num,
            value = entity:GetBodygroup(group.id)
        }
    end
    for _,name in ipairs(entity:GetMaterials()) do
        local material = Material(name)
        local texture = material:GetTexture('$basetexture')
        local failed = material:IsError() or not texture or texture:IsError()
        report.materials[#report.materials + 1] = {name = name, error = failed}
        if failed then report.material_errors = report.material_errors + 1 end
    end
    for index = 0,entity:GetFlexNum() - 1 do
        report.flexes[#report.flexes + 1] = {
            index = index, name = entity:GetFlexName(index), weight = entity:GetFlexWeight(index)
        }
    end
    local positions = {}
    for _,name in ipairs({'eye_L', 'eye_R'}) do
        local index = entity:LookupBone(name)
        if index then
            local matrix = entity:GetBoneMatrix(index)
            local position = matrix and matrix:GetTranslation()
            local parent = entity:GetBoneParent(index)
            positions[name] = position
            report.bones[name] = {
                index = index, parent = parent >= 0 and entity:GetBoneName(parent) or nil,
                position = vector(position), offset = vector(entity:GetManipulateBonePosition(index)),
                position_getter = vector(entity:GetBonePosition(index))
            }
        end
    end
    local id = entity:LookupAttachment('eyes')
    report.eye_attachment = id
    local attachment = id > 0 and entity:GetAttachment(id)
    if attachment then
        report.attachment_position = vector(attachment.Pos)
        if positions.eye_L and positions.eye_R then
            local center = (positions.eye_L + positions.eye_R) * 0.5
            local delta = center - attachment.Pos
            report.eye_center = vector(center)
            report.eye_center_error = delta:Length()
            report.horizontal = delta:Dot(attachment.Ang:Right())
            report.vertical = delta:Dot(attachment.Ang:Up())
            report.depth = delta:Dot(attachment.Ang:Forward())
        end
    end
    return report
end
