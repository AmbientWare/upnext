-- Atomic job cancellation
-- KEYS[1] = stream_key (for XACK)
-- KEYS[2] = result_key (for storing cancellation result)
-- KEYS[3] = job_key (to delete)
-- KEYS[4] = job_index_key (to delete)
-- KEYS[5] = pubsub_channel (for notification)
-- ARGV[1] = consumer_group
-- ARGV[2] = message_id (can be empty)
-- ARGV[3] = result_data (JSON with cancelled status)
-- ARGV[4] = result_ttl
--
-- Returns: number of operations completed

local stream_key = KEYS[1]
local result_key = KEYS[2]
local job_key = KEYS[3]
local job_index_key = KEYS[4]
local pubsub_channel = KEYS[5]

local consumer_group = ARGV[1]
local message_id = ARGV[2]
local result_data = ARGV[3]
local result_ttl = tonumber(ARGV[4])

local ops = 0

-- ACK the message if we have a message_id
if message_id and message_id ~= "" then
    redis.call("XACK", stream_key, consumer_group, message_id)
    ops = ops + 1
end

-- Store cancellation result with TTL
redis.call("SETEX", result_key, result_ttl, result_data)
ops = ops + 1

-- Delete job data
redis.call("DEL", job_key)
ops = ops + 1
redis.call("DEL", job_index_key)
ops = ops + 1

-- Publish cancellation notification
redis.call("PUBLISH", pubsub_channel, "cancelled")
ops = ops + 1

return ops
