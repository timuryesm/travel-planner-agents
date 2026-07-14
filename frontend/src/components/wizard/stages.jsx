// ─────────────────────────────────────────────────────────────────────────────
// Stage components — barrel file
// ─────────────────────────────────────────────────────────────────────────────
// All eight stages are now real implementations. No placeholders remain.
//
//   12a  SetupStage, DestinationStage
//   12b  FlightsStage, AccommodationStage, ActivitiesStage
//   12c  DailyPlanStage, ReconciliationStage, FinalStage

export { default as SetupStage }          from './SetupStage'
export { default as DestinationStage }    from './DestinationStage'
export { default as FlightsStage }        from './FlightsStage'
export { default as AccommodationStage }  from './AccommodationStage'
export { default as ActivitiesStage }     from './ActivitiesStage'
export { default as DailyPlanStage }      from './DailyPlanStage'
export { default as ReconciliationStage } from './ReconciliationStage'
export { default as FinalStage }          from './FinalStage'