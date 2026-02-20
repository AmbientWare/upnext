-- Atomic job completion
-- KEYS[1] = stream_key (for XACK)
-- KEYS[2] = job_key (for storing terminal payload)
-- KEYS[3] = job_index_key (for job ID -> key mapping)
-- KEYS[4] = dedup_key (to remove dedup entry)
-- KEYS[5] = pubsub_channel (for notification)
-- ARGV[1] = consumer_group
-- ARGV[2] = message_id (can be empty)
-- ARGV[3] = job_data (JSON)
-- ARGV[4] = job_ttl
-- ARGV[5] = dedup_value (job.key, can be empty)
-- ARGV[6] = status (for pubsub)
--
-- Returns: number of operations completed

local stream_key = KEYS[1]
local job_key = KEYS[2]
local job_index_key = KEYS[3]
local dedup_key = KEYS[4]
local pubsub_channel = KEYS[5]

local consumer_group = ARGV[1]
local message_id = ARGV[2]
local job_data = ARGV[3]
local job_ttl = tonumber(ARGV[4])
local dedup_value = ARGV[5]
local status = ARGV[6]

local ops = 0

-- ACK the message if we have a message_id
if message_id and message_id ~= "" then
    redis.call("XACK", stream_key, consumer_group, message_id)
    ops = ops + 1
end

-- Store terminal job payload with TTL.
redis.call("SETEX", job_key, job_ttl, job_data)
ops = ops + 1

-- Refresh id index with matching TTL.
redis.call("SETEX", job_index_key, job_ttl, job_key)
ops = ops + 1

-- Remove dedup key if present
if dedup_value and dedup_value ~= "" then
    redis.call("SREM", dedup_key, dedup_value)
    ops = ops + 1
end

-- Publish completion notification
redis.call("PUBLISH", pubsub_channel, status)
ops = ops + 1

return ops
