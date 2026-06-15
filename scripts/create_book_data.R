## create_book_data.R
##
## Builds the synthetic "Harlan Reservoir 2022" teaching dataset used
## throughout Modern Creel Survey Analysis in R.
##
## Source: Calamus Reservoir 2018 creel survey (Nebraska Game and Parks
## Commission). Structure preserved; counts, fish numbers, and trip
## durations jittered so the synthetic data do not replicate the real
## survey record exactly.
##
## Outputs (saved to data/):
##   harlan_counts.rds       -- instantaneous count observations
##   harlan_interviews.rds   -- party-level interview records
##   harlan_catch.rds        -- species-level catch within each party
##   harlan_schedule.rds     -- full sampling frame (all days + sampled flag)
##
## Run once from the project root:
##   source("scripts/create_book_data.R")

library(readr)
library(dplyr)
library(lubridate)
library(tidyr)

set.seed(20220601)           # reproducible randomization

CALAMUS_DATA <- "/Users/cchizinski2/Downloads/aiffd-creel-chapter-master/data"
DATA_OUT     <- here::here("data")
dir.create(DATA_OUT, showWarnings = FALSE)

## ── helpers ──────────────────────────────────────────────────────────────────

jitter_pos <- function(x, frac = 0.20) {
  # Multiplicative noise, result clamped >= 0
  pmax(0, x * (1 + runif(length(x), -frac, frac)))
}

jitter_int <- function(x, spread = 2L) {
  # Additive integer noise, result clamped >= 0
  pmax(0L, as.integer(round(x + sample(-spread:spread, length(x), replace = TRUE))))
}

shift_year <- function(dt, from = 2018L, to = 2022L) {
  year(dt) <- to
  dt
}

## ── 1. counts ────────────────────────────────────────────────────────────────

raw_counts <- read_csv(
  file.path(CALAMUS_DATA, "Counts.csv"),
  show_col_types = FALSE
) |>
  mutate(date = as.Date(date))

harlan_counts <- raw_counts |>
  mutate(
    date        = shift_year(date),
    reservoir   = "Harlan Reservoir",
    # add ±20 % multiplicative noise to each count column
    bankAnglers = as.integer(round(jitter_pos(bankAnglers, 0.20))),
    anglerBoats = as.integer(round(jitter_pos(anglerBoats, 0.20))),
    boatAnglers = as.integer(round(jitter_pos(boatAnglers, 0.20))),
    # day-type derived from date
    day_type    = if_else(wday(date) %in% c(1L, 7L), "weekend", "weekday"),
    # rename for tidycreel schema compatibility
    count_time  = countTime,
    section     = as.character(section)
  ) |>
  select(reservoir, date, day_type, period, section, count_time,
         bank_anglers = bankAnglers,
         angler_boats = anglerBoats,
         boat_anglers = boatAnglers)

## ── 2. interviews ─────────────────────────────────────────────────────────────

raw_int <- read_csv(
  file.path(CALAMUS_DATA, "Interviews.csv"),
  show_col_types = FALSE
) |>
  mutate(date = as.Date(date))

## One row per unique party × date × period (collapse multi-species rows first)
party_level <- raw_int |>
  distinct(date, period, section, partyID,
           numAnglers, anglerType, anglerMethod,
           timeFishedHours, timeFishedMins, tripType)

harlan_interviews <- party_level |>
  mutate(
    date             = shift_year(date),
    reservoir        = "Harlan Reservoir",
    day_type         = if_else(wday(date) %in% c(1L, 7L), "weekend", "weekday"),
    # jitter trip duration ±15 %
    hours_fished     = round(jitter_pos(timeFishedHours, 0.15), 2),
    hours_fished     = pmax(0.1, hours_fished),
    n_anglers        = numAnglers,
    angler_type      = tolower(anglerType),
    angler_method    = anglerMethod,
    # tripType 1 = complete, 2 = incomplete
    trip_status      = if_else(tripType == 1L, "complete", "incomplete"),
    section          = as.character(section),
    interview_id     = row_number()
  ) |>
  select(reservoir, date, day_type, period, section, interview_id,
         party_id = partyID, n_anglers, angler_type, angler_method,
         hours_fished, trip_status)

## ── 3. catch ──────────────────────────────────────────────────────────────────

## Map partyID → interview_id using the party_level key
id_map <- party_level |>
  mutate(
    date         = shift_year(date),
    interview_id = row_number()
  ) |>
  select(date_orig = date, period, section, party_id = partyID, interview_id)

## Species renaming: keep Nebraska species, add slight proportion shuffle
species_remap <- c(
  "Channel Catfish"              = "Channel Catfish",
  "Common Carp"                  = "Common Carp",
  "Crappie"                      = "Crappie",
  "Freshwater Drum"              = "Freshwater Drum",
  "Gizzard Shad"                 = "Gizzard Shad",
  "Muskellunge"                  = "Muskellunge",
  "Northern Pike"                = "Northern Pike",
  "Striped Bass Hybrid (wiper)"  = "Wiper",
  "Walleye"                      = "Walleye",
  "White Bass"                   = "White Bass",
  "Yellow Perch"                 = "Yellow Perch"
)

harlan_catch <- raw_int |>
  filter(!is.na(numFish), !is.na(catchType)) |>
  mutate(date = shift_year(as.Date(date))) |>
  left_join(
    id_map,
    by = c("partyID" = "party_id", "date" = "date_orig",
           "period", "section")
  ) |>
  mutate(
    species    = recode(speciesCaught, !!!species_remap),
    species    = coalesce(species, speciesCaught),
    catch_type = case_when(
      catchType == "H" ~ "harvested",
      catchType == "R" ~ "released",
      TRUE             ~ NA_character_
    ),
    # jitter fish counts ±1-2 fish, floor at 0
    n_fish     = jitter_int(as.integer(numFish), spread = 2L)
  ) |>
  filter(!is.na(interview_id), !is.na(species), !is.na(catch_type)) |>
  select(interview_id, species, catch_type, n_fish)

## ── 4. sampling frame (schedule) ─────────────────────────────────────────────

all_dates <- seq(
  from = as.Date("2022-04-02"),
  to   = as.Date("2022-10-29"),
  by   = "day"
)

sampled_dates <- unique(harlan_counts$date)

harlan_schedule <- tibble(date = all_dates) |>
  mutate(
    reservoir = "Harlan Reservoir",
    day_type  = if_else(wday(date) %in% c(1L, 7L), "weekend", "weekday"),
    sampled   = date %in% sampled_dates
  )

## ── 5. save ──────────────────────────────────────────────────────────────────

saveRDS(harlan_counts,     file.path(DATA_OUT, "harlan_counts.rds"))
saveRDS(harlan_interviews, file.path(DATA_OUT, "harlan_interviews.rds"))
saveRDS(harlan_catch,      file.path(DATA_OUT, "harlan_catch.rds"))
saveRDS(harlan_schedule,   file.path(DATA_OUT, "harlan_schedule.rds"))

cat("Saved to", DATA_OUT, "\n")
cat("  harlan_counts:    ", nrow(harlan_counts),     "rows\n")
cat("  harlan_interviews:", nrow(harlan_interviews),  "rows\n")
cat("  harlan_catch:     ", nrow(harlan_catch),       "rows\n")
cat("  harlan_schedule:  ", nrow(harlan_schedule),    "rows\n")

## ── 6. quick sanity check ────────────────────────────────────────────────────

cat("\nDate range (counts):",
    format(range(harlan_counts$date)), "\n")
cat("Day types (schedule):",
    paste(table(harlan_schedule$day_type), collapse = " / "),
    "(weekday / weekend)\n")
cat("Sampled days:", sum(harlan_schedule$sampled),
    "of", nrow(harlan_schedule), "total\n")
cat("Species in catch:", paste(sort(unique(harlan_catch$species)), collapse = ", "), "\n")
