// jscs:disable requireCapitalizedConstructors

define([
        'backbone',
        'backbone.relational',
        'backbone.super',
        'backbone.validation',
        'jquery',
        'jquery-cookie',
        'underscore',
        'moment',
        'models/course_model'
    ],
    function (Backbone,
              BackboneRelational,
              BackboneSuper,
              BackboneValidation,
              $,
              $cookie,
              _,
              moment,
              Course) {
        'use strict';

        _.extend(Backbone.Model.prototype, Backbone.Validation.mixin);

        _.extend(Backbone.Validation.patterns, {
            courseId: /[^/+]+(\/|\+)[^/+]+(\/|\+)[^/]+/
        });

        _.extend(Backbone.Validation.messages, {
            courseId: gettext('The course ID is invalid.')
        });

        return Backbone.RelationalModel.extend({
            urlRoot: '/api/v2/coupons/',

            dateFormat: 'MM/DD/YYYY',

            defaults: {
            },

            validation: {
                course_id: {
                    pattern: 'courseId'
                },
                title: {
                    required: true
                },
                client_username: {
                    required: true
                },
                seat_type: {
                    required: true
                },
                price: {
                    required: function () {
                        return this.isEnrollmentCode();
                    }
                },
                benefit_value: {
                    required: function () {
                        return this.isDiscountCode();
                    }
                },
                start_date: function (val) {
                    if (_.isEmpty(val)) {
                        return gettext('Start date is required');
                    }
                    var isValid = moment(val, this.dateFormat).isValid();
                    if (!isValid) {
                        return gettext('Start date is invalid');
                    }
                    var endDate = moment(this.get('end_date'), this.dateFormat);
                    var isBefore = moment(val, this.dateFormat).isBefore(endDate);
                    if (endDate && !isBefore) {
                        return gettext('Must occur before end date');
                    }
                },
                end_date: function (val) {
                    if (_.isEmpty(val)) {
                        return gettext('End date is required');
                    }
                    var isValid = moment(val, this.dateFormat).isValid();
                    if (!isValid) {
                        return gettext('End date is invalid');
                    }
                    var startDate = moment(this.get('start_date'), this.dateFormat);
                    var isAfter = moment(val, this.dateFormat).isAfter(startDate);
                    if (startDate && !isAfter) {
                        return gettext('Must occur after start date');
                    }
                }
            },

            isEnrollmentCode: function () {
                return this.get('code_type') === 'enrollment' ;
            },

            isDiscountCode: function () {
                return this.get('code_type') === 'discount' ;
            },

            labels: {
            },

            relations: [
                {
                    type: Backbone.HasOne,
                    key: 'course',
                    relatedModel: Course,
                    includeInJSON: false
                },
            ],

            initialize: function () {
                this.on('change:voucher_type', this.changeVoucherType, this);
                this.on('change:course_id', this.loadCourse, this);
                this.set('quantity', 1);
            },

            loadCourse: function (model, value) {
                if (this.isValid('course_id')) {
                    this.set('course', Course.findOrCreate({id: value}));
                    this.listenTo(this.get('course'), 'change', this.fillFromCourse, this);
                    this.get('course').fetch({data: {include_products: true}});
                }
            },

            fillFromCourse: function (course) {
                var seatTypes = _.map(course.seats(), function(val) {
                    return {
                        value: val.get('certificate_type'),
                        label: val.getSeatTypeDisplayName()
                    };
                });
                this.set('seatTypes', seatTypes);

                // triggers update for seat_type selectOptions
                this.set('seat_type', seatTypes[0].value);
            },

            changeVoucherType: function (model, value) {
                if (value === 'Single use') {
                    this.set('quantity', 1);
                }
            },

            save: function (options) {
                _.defaults(options || (options = {}), {
                    type: 'POST',
                    // The API requires a CSRF token for all POST requests using session authentication.
                    headers: {'X-CSRFToken': $.cookie('ecommerce_csrftoken')},
                    contentType: 'application/json'
                });

                var seat = this.get('course').get('products').findWhere({
                    certificate_type: this.get('seat_type')
                });

                var stockRecordIds = _.map(seat.get('stockrecords'), _.compose(parseInt, _.property('id')));

                var data = {
                    title: this.get('title'),
                    client_username: this.get('client_username'),
                    start_date: this.get('start_date'),
                    end_date: this.get('end_date'),
                    stock_record_ids: stockRecordIds,
                    code: this.get('code') || '',
                    voucher_type: this.get('voucher_type'),
                    quantity: parseInt(this.get('quantity'))
                };

                if (data.voucher_type !== 'Single use' || _.isEmpty(this.get('quantity'))) {
                    data.quantity = 1;
                }

                switch (this.get('code_type')) {
                case 'enrollment':
                    data.price = parseFloat(this.get('price'));
                    data.benefit_type = 'Percentage';
                    data.benefit_value = 100;
                break;
                case 'discount':
                    data.price = 0;
                    data.benefit_type = this.get('benefit_type');
                    data.benefit_value = parseFloat(this.get('benefit_value'));
                break;
                }

                options.data = JSON.stringify(data);
                return this._super(null, options);
            }
        });
    }
);