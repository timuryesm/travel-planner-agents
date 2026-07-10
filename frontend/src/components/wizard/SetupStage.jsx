import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  StageCard, Field, Input, Textarea, Select, Segmented, Toggle, StageActions,
} from './primitives'

// ─────────────────────────────────────────────────────────────────────────────
// SetupStage — the seed input for the whole trip
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload must validate against SetupCommitData (Phase B):
//   origin           str     required
//   departure_date   date    required   (ISO YYYY-MM-DD)
//   return_date      date    required
//   num_travelers    int     required   (>= 1)
//   travel_type      enum    required   'relax' | 'active' | 'hybrid'
//   budget_amount    float?  optional
//   budget_currency  str     default 'USD'
//   with_kids        bool    default false
//   preferences_text str?    optional
//   multi_city       bool    default false
//
// Trip-level stage: cannot be skipped (the whole wizard depends on it), so
// showSkip=false. FORWARD is also hidden — advancing without a setup commit
// would leave every downstream stage without dates or budget.

const CURRENCIES = ['USD', 'CAD', 'EUR', 'GBP', 'JPY', 'AUD']

// Today in YYYY-MM-DD, used as the min for date inputs
function todayISO() {
  return new Date().toISOString().slice(0, 10)
}

export default function SetupStage({ commit, commitData, transitioning }) {
  const { t } = useTranslation()

  // Prefill from an existing commit when the user navigates back to this stage
  const [origin, setOrigin] = useState(commitData?.origin ?? '')
  const [departureDate, setDepartureDate] = useState(commitData?.departure_date ?? '')
  const [returnDate, setReturnDate] = useState(commitData?.return_date ?? '')
  const [numTravelers, setNumTravelers] = useState(commitData?.num_travelers ?? 1)
  const [travelType, setTravelType] = useState(commitData?.travel_type ?? 'hybrid')
  const [budgetAmount, setBudgetAmount] = useState(commitData?.budget_amount ?? '')
  const [budgetCurrency, setBudgetCurrency] = useState(commitData?.budget_currency ?? 'USD')
  const [withKids, setWithKids] = useState(commitData?.with_kids ?? false)
  const [multiCity, setMultiCity] = useState(commitData?.multi_city ?? false)
  const [preferences, setPreferences] = useState(commitData?.preferences_text ?? '')

  // Required fields present, and return date not before departure
  const datesValid =
    departureDate && returnDate && returnDate >= departureDate
  const valid =
    origin.trim().length > 0 && datesValid && Number(numTravelers) >= 1

  function handleConfirm() {
    commit({
      origin: origin.trim(),
      departure_date: departureDate,
      return_date: returnDate,
      num_travelers: Number(numTravelers),
      travel_type: travelType,
      // Send null rather than '' so Pydantic's Optional[float] accepts it
      budget_amount: budgetAmount === '' ? null : Number(budgetAmount),
      budget_currency: budgetCurrency,
      with_kids: withKids,
      preferences_text: preferences.trim() || null,
      multi_city: multiCity,
    })
  }

  return (
    <StageCard title={t('setup.title')} subtitle={t('setup.subtitle')}>
      <div className="flex flex-col gap-5">

        {/* Origin */}
        <Field label={t('setup.origin')}>
          <Input
            value={origin}
            onChange={setOrigin}
            placeholder={t('setup.originPlaceholder')}
          />
        </Field>

        {/* Dates */}
        <div className="grid grid-cols-2 gap-4">
          <Field label={t('setup.departureDate')}>
            <Input
              type="date"
              value={departureDate}
              onChange={setDepartureDate}
              min={todayISO()}
            />
          </Field>
          <Field label={t('setup.returnDate')}>
            <Input
              type="date"
              value={returnDate}
              onChange={setReturnDate}
              min={departureDate || todayISO()}
            />
          </Field>
        </div>

        {/* Travelers + travel type */}
        <div className="grid grid-cols-2 gap-4">
          <Field label={t('setup.travelers')}>
            <Input
              type="number"
              value={numTravelers}
              onChange={setNumTravelers}
              min={1}
            />
          </Field>
          <Field label={t('setup.currency')}>
            <Select
              value={budgetCurrency}
              onChange={setBudgetCurrency}
              options={CURRENCIES.map((c) => ({ value: c, label: c }))}
            />
          </Field>
        </div>

        {/* Travel type */}
        <Field label={t('setup.travelType')}>
          <Segmented
            value={travelType}
            onChange={setTravelType}
            options={[
              { value: 'relax',  label: t('setup.travelTypeRelax') },
              { value: 'active', label: t('setup.travelTypeActive') },
              { value: 'hybrid', label: t('setup.travelTypeHybrid') },
            ]}
          />
        </Field>

        {/* Budget */}
        <Field label={t('setup.budget')} hint={`(${t('common.optional')})`}>
          <Input
            type="number"
            value={budgetAmount}
            onChange={setBudgetAmount}
            placeholder={t('setup.budgetPlaceholder')}
            min={0}
          />
        </Field>

        {/* Toggles */}
        <div className="flex flex-col gap-3 py-1">
          <Toggle
            checked={withKids}
            onChange={setWithKids}
            label={t('setup.withKids')}
          />
          <Toggle
            checked={multiCity}
            onChange={setMultiCity}
            label={t('setup.multiCity')}
          />
        </div>

        {/* Preferences */}
        <Field label={t('setup.preferences')} hint={`(${t('common.optional')})`}>
          <Textarea
            value={preferences}
            onChange={setPreferences}
            placeholder={t('setup.preferencesPlaceholder')}
          />
        </Field>
      </div>

      {/* Setup cannot be skipped or forwarded past — everything depends on it */}
      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!valid}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}