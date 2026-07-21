// ─────────────────────────────────────────────────────────────────────────────
// Stage components — barrel file
// ─────────────────────────────────────────────────────────────────────────────
// Hub-and-spoke stages:
//   setup → country → city → flights → [intercity] → accommodation
//         → activities[0..N] → daily_plan → final
//
// DestinationStage split into CountryStage + CityStage.
// ReconciliationStage dropped — with only activities at stop level there was
// nothing left for it to nag about.
// IntercityStage arrives in Track 2 (step 18).

export { default as SetupStage }         from './SetupStage'
export { default as CountryStage }       from './CountryStage'
export { default as CityStage }          from './CityStage'
export { default as IntercityStage } from './IntercityStage'
export { default as FlightsStage }       from './FlightsStage'
export { default as AccommodationStage } from './AccommodationStage'
export { default as ActivitiesStage }    from './ActivitiesStage'
export { default as DailyPlanStage }     from './DailyPlanStage'
export { default as FinalStage }         from './FinalStage'