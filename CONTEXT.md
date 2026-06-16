# Running Coach Context

This document names the domain concepts that should stay stable across code,
tests, prompts, and agent reviews.

## Athlete

The local user profile for the app. It includes age, sex, weight, height, max
heart rate, training availability, injury notes, and the current running date or
goal date context.

## Activity

A Garmin-style workout row. `external_id` maps to Garmin `activityId`.
`activity_name` maps to Garmin `activityName` and is the preferred display
title. Activity detail data may include track points and laps.

## Health Metric

A daily recovery row containing sleep, resting heart rate, HRV, stress, body
battery, recovery time, and VO2max when available. Garmin recovery time must
come only from explicitly named recovery fields.

## Goal

An athlete target such as 5K, 10K, half, or running PB. One goal is active at a
time and is used by predictions, readiness, coaching decisions, and digest copy.

## Training Snapshot

The deterministic analytics summary produced from activities, health metrics,
the athlete profile, and the active goal. It feeds dashboard metrics, prediction
history, coaching prompts, and fallback coaching decisions.

## Prediction Snapshot

A stored prediction after a run or on a date for an active goal. It represents
the prediction using data available up to that activity/date, not future data.

## Coaching Decision

A daily or weekly structured coaching output. It combines deterministic rules,
calendar context, active goal context, training snapshot evidence, optional LLM
generation, and optional Telegram delivery.

## Activity Coach Opinion

A one-time stored LLM interpretation of a single running workout. It is generated
only when enough activity context exists and is not regenerated automatically.
