export interface paths {
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_v1_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/controls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Controls */
        get: operations["controls_api_v1_controls_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/episodes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Episodes */
        get: operations["episodes_api_v1_episodes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/replay/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Replay Start */
        post: operations["replay_start_api_v1_replay_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/replay/advance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Replay Advance */
        post: operations["replay_advance_api_v1_replay_advance_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/snapshots/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Current Snapshot */
        get: operations["current_snapshot_api_v1_snapshots_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/snapshots/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Snapshot */
        get: operations["snapshot_api_v1_snapshots__snapshot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/decisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Decisions */
        get: operations["decisions_api_v1_decisions_get"];
        put?: never;
        /** Create Decision */
        post: operations["create_decision_api_v1_decisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/scenarios/evaluate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Evaluate Scenario */
        post: operations["evaluate_scenario_api_v1_scenarios_evaluate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/decisions/{decision_id}/save": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Save Decision */
        post: operations["save_decision_api_v1_decisions__decision_id__save_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/decisions/{decision_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Decision */
        get: operations["decision_api_v1_decisions__decision_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * Action
         * @description Alternative next action; changes are absolute current setpoints.
         */
        Action: {
            /**
             * Action Id
             * Format: uuid
             */
            action_id: string;
            /** Label */
            label: string;
            origin: components["schemas"]["ActionOrigin"];
            /** Changes */
            changes?: {
                [key: string]: number;
            };
        };
        /** ActionInput */
        ActionInput: {
            /**
             * Label
             * @default Вариант оператора
             */
            label: string;
            /** Changes */
            changes?: {
                [key: string]: number;
            };
        };
        /**
         * ActionOrigin
         * @enum {string}
         */
        ActionOrigin: "baseline" | "system" | "operator";
        /**
         * Admissibility
         * @enum {string}
         */
        Admissibility: "admissible" | "rejected" | "not_assessable";
        /**
         * Applicability
         * @enum {string}
         */
        Applicability: "supported" | "unsupported" | "insufficient_data";
        /**
         * CheckCategory
         * @enum {string}
         */
        CheckCategory: "data" | "quality" | "reliability" | "control" | "applicability";
        /** CheckResult */
        CheckResult: {
            /** Code */
            code: string;
            /** Passed */
            passed: boolean | null;
            category: components["schemas"]["CheckCategory"];
            /** Message */
            message: string;
            /** Actual */
            actual?: number | null;
            /** Limit */
            limit?: number | null;
            /** Unit */
            unit?: string | null;
        };
        /** ControlResponse */
        ControlResponse: {
            /** Signal Id */
            signal_id: string;
            /** Label */
            label: string;
            /** Available */
            available: boolean;
            /** Reason */
            reason: string | null;
            /** Unit */
            unit: string | null;
            /** Min */
            min: number | null;
            /** Max */
            max: number | null;
            /** Step */
            step: number | null;
            /** Source */
            source: string;
        };
        /** ControlsResponse */
        ControlsResponse: {
            /** Constraint Version */
            constraint_version: string;
            /** Controls */
            controls: components["schemas"]["ControlResponse"][];
            /** Review Issues */
            review_issues: string[];
        };
        /** Decision */
        Decision: {
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /** Horizon Minutes */
            horizon_minutes: number;
            status: components["schemas"]["DecisionStatus"];
            baseline: components["schemas"]["ScenarioEvaluation"];
            preferred: components["schemas"]["ScenarioEvaluation"] | null;
            /** Alternatives */
            alternatives: components["schemas"]["ScenarioEvaluation"][];
            /** Rejected Evaluations */
            rejected_evaluations: components["schemas"]["ScenarioEvaluation"][];
            /** Explanation */
            explanation: string[];
            /** Trace */
            trace: components["schemas"]["TraceEntry"][];
            /** Dataset Version */
            dataset_version: string;
            /** Model Version */
            model_version: string;
            /** Constraint Version */
            constraint_version: string;
        };
        /** DecisionListResponse */
        DecisionListResponse: {
            /** Items */
            items: components["schemas"]["DecisionSummary"][];
        };
        /** DecisionRequest */
        DecisionRequest: {
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /**
             * Horizon Minutes
             * @default 60
             * @constant
             */
            horizon_minutes: 60;
            operator_action?: components["schemas"]["ActionInput"] | null;
        };
        /** DecisionResponse */
        DecisionResponse: {
            decision: components["schemas"]["Decision"];
            /**
             * Current Snapshot Id
             * Format: uuid
             */
            current_snapshot_id: string;
            /** Stale */
            stale: boolean;
        };
        /**
         * DecisionStatus
         * @enum {string}
         */
        DecisionStatus: "change_recommended" | "no_change" | "insufficient_data" | "no_feasible_option";
        /** DecisionSummary */
        DecisionSummary: {
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            status: components["schemas"]["DecisionStatus"];
            /** Saved */
            saved: boolean;
        };
        /** EpisodeResponse */
        EpisodeResponse: {
            /** Episode Id */
            episode_id: string;
            /** Name */
            name: string;
            /**
             * Start
             * Format: date-time
             */
            start: string;
            /**
             * End
             * Format: date-time
             */
            end: string;
            /** Step Minutes */
            step_minutes: number;
            /** Synthetic */
            synthetic: boolean;
            /** Limitations */
            limitations: string[];
        };
        /** EpisodesResponse */
        EpisodesResponse: {
            /** Version */
            version: string;
            /** Episodes */
            episodes: components["schemas"]["EpisodeResponse"][];
        };
        /**
         * EstimateBasis
         * @enum {string}
         */
        EstimateBasis: "measured" | "predicted" | "proxy" | "unavailable";
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /** Ready */
            ready: boolean;
            /** Model Ready */
            model_ready: boolean;
            /** Data Ready */
            data_ready: boolean;
            /** Database Ready */
            database_ready: boolean;
            /**
             * Issues
             * @default []
             */
            issues: string[];
        };
        /**
         * HistoryRecord
         * @description A historical observation included in a snapshot history window.
         */
        HistoryRecord: {
            /** Signal Id */
            signal_id: string;
            /**
             * Measured At
             * Format: date-time
             */
            measured_at: string;
            /** Value */
            value: number;
        };
        /**
         * Measurement
         * @description One value together with its event time, availability, and quality.
         */
        Measurement: {
            /** Value */
            value: number | null;
            /** Unit */
            unit: string | null;
            /** Source */
            source: string;
            /**
             * Measured At
             * Format: date-time
             */
            measured_at: string;
            /**
             * Available At
             * Format: date-time
             */
            available_at: string;
            /** Age Seconds */
            age_seconds: number;
            quality: components["schemas"]["MeasurementQuality"];
            /**
             * Issues
             * @default []
             */
            issues: string[];
        };
        /**
         * MeasurementQuality
         * @enum {string}
         */
        MeasurementQuality: "valid" | "suspect" | "missing";
        /** MetricEstimate */
        MetricEstimate: {
            /** Value */
            value: number | null;
            /** Unit */
            unit: string | null;
            basis: components["schemas"]["EstimateBasis"];
            /** Explanation */
            explanation: string;
            /** Lower */
            lower?: number | null;
            /** Upper */
            upper?: number | null;
        };
        /** ProcessSnapshot */
        ProcessSnapshot: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /**
             * As Of
             * Format: date-time
             */
            as_of: string;
            mode: components["schemas"]["SnapshotMode"];
            /** Dataset Version */
            dataset_version: string;
            /** Values */
            values: {
                [key: string]: components["schemas"]["Measurement"];
            };
            /** History */
            history: components["schemas"]["HistoryRecord"][];
            /**
             * Issues
             * @default []
             */
            issues: string[];
            /** Completeness */
            completeness: number;
        };
        /** QualityAssessment */
        QualityAssessment: {
            /** Target */
            target: string;
            /**
             * Forecast At
             * Format: date-time
             */
            forecast_at: string;
            /** Prediction */
            prediction: number | null;
            /** Unit */
            unit: string;
            /** Lower */
            lower: number | null;
            /** Upper */
            upper: number | null;
            /** Interval Coverage Target */
            interval_coverage_target: number | null;
            applicability: components["schemas"]["Applicability"];
            /** Reasons */
            reasons: string[];
            /** Model Version */
            model_version: string;
        };
        /** ReliabilityAssessment */
        ReliabilityAssessment: {
            /** Severity Index */
            severity_index: number | null;
            /** Factors */
            factors: components["schemas"]["ReliabilityFactor"][];
            /** Transition Assessed */
            transition_assessed: boolean;
            /** Limitations */
            limitations: string[];
        };
        /** ReliabilityFactor */
        ReliabilityFactor: {
            /** Name */
            name: string;
            /** Contribution */
            contribution: number;
            /** Explanation */
            explanation: string;
        };
        /** ReplayAdvanceRequest */
        ReplayAdvanceRequest: {
            /**
             * Expected Snapshot Id
             * Format: uuid
             */
            expected_snapshot_id: string;
        };
        /** ReplayStartRequest */
        ReplayStartRequest: {
            /** Episode Id */
            episode_id?: string | null;
        };
        /** SaveDecisionResponse */
        SaveDecisionResponse: {
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Saved
             * @default true
             * @constant
             */
            saved: true;
        };
        /** ScenarioEvaluation */
        ScenarioEvaluation: {
            /**
             * Evaluation Id
             * Format: uuid
             */
            evaluation_id: string;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /** Horizon Minutes */
            horizon_minutes: number;
            action: components["schemas"]["Action"];
            quality: components["schemas"]["QualityAssessment"];
            reliability: components["schemas"]["ReliabilityAssessment"];
            throughput: components["schemas"]["MetricEstimate"];
            cost: components["schemas"]["MetricEstimate"];
            /** Checks */
            checks: components["schemas"]["CheckResult"][];
            admissibility: components["schemas"]["Admissibility"];
            /** Reasons */
            reasons: string[];
            /** Model Version */
            model_version: string;
            /** Constraint Version */
            constraint_version: string;
        };
        /** ScenarioRequest */
        ScenarioRequest: {
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /**
             * Horizon Minutes
             * @default 60
             * @constant
             */
            horizon_minutes: 60;
            /** Changes */
            changes: {
                [key: string]: number;
            };
        };
        /** ScenarioResponse */
        ScenarioResponse: {
            evaluation: components["schemas"]["ScenarioEvaluation"];
            /**
             * Current Snapshot Id
             * Format: uuid
             */
            current_snapshot_id: string;
            /** Stale */
            stale: boolean;
        };
        /**
         * SnapshotMode
         * @enum {string}
         */
        SnapshotMode: "replay" | "manual";
        /** SnapshotResponse */
        SnapshotResponse: {
            snapshot: components["schemas"]["ProcessSnapshot"];
            /**
             * Current Snapshot Id
             * Format: uuid
             */
            current_snapshot_id: string;
        };
        /** StoredDecisionResponse */
        StoredDecisionResponse: {
            decision: components["schemas"]["Decision"];
            /**
             * Current Snapshot Id
             * Format: uuid
             */
            current_snapshot_id: string;
            /** Stale */
            stale: boolean;
        };
        /** TraceEntry */
        TraceEntry: {
            /** Role */
            role: string;
            /** Input Ids */
            input_ids: string[];
            /** Output Summary */
            output_summary: string;
            /**
             * Check Codes
             * @default []
             */
            check_codes: string[];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_api_v1_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    controls_api_v1_controls_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlsResponse"];
                };
            };
        };
    };
    episodes_api_v1_episodes_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EpisodesResponse"];
                };
            };
        };
    };
    replay_start_api_v1_replay_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplayStartRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    replay_advance_api_v1_replay_advance_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplayAdvanceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    current_snapshot_api_v1_snapshots_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotResponse"];
                };
            };
        };
    };
    snapshot_api_v1_snapshots__snapshot_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decisions_api_v1_decisions_get: {
        parameters: {
            query?: {
                saved_only?: boolean;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecisionListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_decision_api_v1_decisions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecisionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    evaluate_scenario_api_v1_scenarios_evaluate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScenarioRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScenarioResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_decision_api_v1_decisions__decision_id__save_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                decision_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SaveDecisionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decision_api_v1_decisions__decision_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                decision_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StoredDecisionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
