-- Atomic cron seed mutation.
-- KEYS[1] = cron_registry_key (HASH)
-- KEYS[2] = cron_window_reservation_key (STRING)
-- KEYS[3] = scheduled_key (ZSET)
-- KEYS[4] = job_key (STRING)
-- KEYS[5] = job_index_key (STRING)
-- KEYS[6] = cron_cursor_key (HASH)
-- ARGV[1] = cron_key (e.g., "cron:fn.key")
-- ARGV[2] = function_name
-- ARGV[3] = job_id
-- ARGV[4] = next_run_at
-- ARGV[5] = job_ttl_seconds
-- ARGV[6] = reservation_ttl_seconds
-- ARGV[7] = job_data (JSON)
-- ARGV[8] = cursor_payload (JSON)
-- ARGV[9] = key_prefix (e.g., "upnext")
--
-- Returns:
--   "SEEDED:<job_id>"
--   "ALREADY_REGISTERED:<owner_job_id>"
--   "WINDOW_OWNED:<owner_job_id>"

local cron_registry_key = KEYS[1]
local reservation_key = KEYS[2]
local scheduled_key = KEYS[3]
local job_key = KEYS[4]
local job_index_key = KEYS[5]
local cron_cursor_key = KEYS[6]

local cron_key = ARGV[1]
local function_name = ARGV[2]
local job_id = ARGV[3]
local next_run_at = tonumber(ARGV[4])
local job_ttl = tonumber(ARGV[5])
local reservation_ttl = tonumber(ARGV[6])
local job_data = ARGV[7]
local cursor_payload = ARGV[8]
local key_prefix = ARGV[9]

local function owner_is_runnable(owner_id)
    if not owner_id or owner_id == "" then
        return false
    end

    local scheduled_score = redis.call("ZSCORE", scheduled_key, owner_id)
    if scheduled_score then
        return true
    end

    local owner_job_key = key_prefix .. ":job:" .. function_name .. ":" .. owner_id
    if redis.call("EXISTS", owner_job_key) ~= 1 then
        return false
    end

    local owner_index_key = key_prefix .. ":job_index:" .. owner_id
    local indexed_job_key = redis.call("GET", owner_index_key)
    if indexed_job_key and indexed_job_key == owner_job_key then
        return true
    end

    return false
end

local function reserve_window()
    local reserved = redis.call("SET", reservation_key, job_id, "NX", "EX", reservation_ttl)
    if reserved then
        return true, job_id
    end

    local owner_id = redis.call("GET", reservation_key)
    if owner_id and owner_is_runnable(owner_id) then
        return false, owner_id
    end

    redis.call("DEL", reservation_key)
    local reclaimed = redis.call("SET", reservation_key, job_id, "NX", "EX", reservation_ttl)
    if reclaimed then
        return true, job_id
    end

    local latest_owner = redis.call("GET", reservation_key)
    if latest_owner then
        return false, latest_owner
    end
    return false, ""
end

local existing_owner = redis.call("HGET", cron_registry_key, cron_key)
if existing_owner then
    return "ALREADY_REGISTERED:" .. existing_owner
end

local reserved, owner_id = reserve_window()
if not reserved then
    if owner_id and owner_id ~= "" then
        redis.call("HSET", cron_registry_key, cron_key, owner_id)
        return "WINDOW_OWNED:" .. owner_id
    end
    return "WINDOW_OWNED:"
end

redis.call("HSET", cron_registry_key, cron_key, job_id)
redis.call("SETEX", job_key, job_ttl, job_data)
redis.call("SETEX", job_index_key, job_ttl, job_key)
redis.call("ZADD", scheduled_key, next_run_at, job_id)
redis.call("HSET", cron_cursor_key, function_name, cursor_payload)

return "SEEDED:" .. job_id
