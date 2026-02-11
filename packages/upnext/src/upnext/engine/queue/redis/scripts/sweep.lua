-- Atomic sweep of scheduled jobs to stream
-- KEYS[1] = scheduled_key (ZSET)
-- KEYS[2] = stream_key (destination)
-- ARGV[1] = current_time (score threshold)
-- ARGV[2] = function_name
-- ARGV[3] = batch_size (max jobs to move)
-- ARGV[4] = stream_maxlen
-- ARGV[5] = key_prefix (e.g., "upnext")
--
-- Returns: number of jobs moved

local scheduled_key = KEYS[1]
local stream_key = KEYS[2]

local current_time = tonumber(ARGV[1])
local function_name = ARGV[2]
local batch_size = tonumber(ARGV[3])
local stream_maxlen = tonumber(ARGV[4])
local key_prefix = ARGV[5]

-- Get due jobs (score <= current_time)
local due_jobs = redis.call("ZRANGEBYSCORE", scheduled_key, "-inf", current_time, "LIMIT", 0, batch_size)

if #due_jobs == 0 then
    return 0
end

local moved = 0

for i, job_id in ipairs(due_jobs) do
    -- Get job data from storage
    local job_key = key_prefix .. ":job:" .. function_name .. ":" .. job_id
    local job_data = redis.call("GET", job_key)

    if job_data then
        -- Add to stream with full job data
        if stream_maxlen > 0 then
            redis.call("XADD", stream_key, "MAXLEN", "~", stream_maxlen, "*",
                       "job_id", job_id, "function", function_name, "data", job_data)
        else
            redis.call("XADD", stream_key, "*",
                       "job_id", job_id, "function", function_name, "data", job_data)
        end
    else
        -- Fallback without data (legacy)
        if stream_maxlen > 0 then
            redis.call("XADD", stream_key, "MAXLEN", "~", stream_maxlen, "*",
                       "job_id", job_id, "function", function_name)
        else
            redis.call("XADD", stream_key, "*",
                       "job_id", job_id, "function", function_name)
        end
    end

    -- Remove from scheduled set
    redis.call("ZREM", scheduled_key, job_id)

    moved = moved + 1
end

return moved
